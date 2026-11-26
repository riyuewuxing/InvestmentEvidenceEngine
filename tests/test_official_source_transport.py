import io
from email.message import Message
from urllib.request import Request

import pytest

from investment_evidence_engine.sources import (
    FED_FIXED_STATEMENT_URLS,
    OfficialRedirectHandler,
    read_official_body,
    validate_official_url,
)


class Response(io.BytesIO):
    def __init__(self, data, headers=None, status=200):
        super().__init__(data)
        self.headers = headers or {}
        self.status = status


@pytest.mark.parametrize("url", [
    "http://www.sse.com.cn/a",
    "https://www.sse.com.cn.evil.example/a",
    "https://www.sse.com.cn@evil.example/a",
    "https://evil@www.sse.com.cn/a",
    "https://www.sse.com.cn:8080/a",
    "https://www.sse.com.cn/a#fragment",
    "https://www.sse.com.cn/a\n",
])
def test_official_host_and_transport_identity(url):
    with pytest.raises(ValueError):
        validate_official_url(url)


def test_redirect_checks_target_before_network():
    handler = OfficialRedirectHandler()
    request = Request("https://www.sse.com.cn/a")
    with pytest.raises(ValueError):
        handler.redirect_request(request, None, 302, "redirect", Message(), "https://evil.example/b")
    approved = handler.redirect_request(request, None, 302, "redirect", Message(),
                                        "https://big5.sse.com.cn/b")
    assert approved.full_url == "https://big5.sse.com.cn/b"


def test_complete_body_exact_bound():
    assert read_official_body(Response(b"abc", {"Content-Length": "3"}), limit=3) == b"abc"
    for data, headers, status in [
        (b"abcd", {}, 200), (b"ab", {"Content-Length": "3"}, 200),
        (b"abc", {"Content-Length": "9"}, 200), (b"abc", {"Content-Length": "bad"}, 200),
        (b"abc", {"Content-Encoding": "gzip"}, 200),
        (b"abc", {"Content-Range": "bytes 0-2/8"}, 200), (b"abc", {}, 206),
    ]:
        with pytest.raises(ValueError):
            read_official_body(Response(data, headers, status), limit=3)


def test_fed_fixed_event_source_scope_only():
    for url in FED_FIXED_STATEMENT_URLS:
        assert validate_official_url(url) == url
        with pytest.raises(ValueError):
            OfficialRedirectHandler().redirect_request(
                Request(url), None, 302, "redirect", Message(), "https://www.sse.com.cn/a")
        with pytest.raises(ValueError):
            validate_official_url(url+"?extra=1")
    for url in ("https://www.federalreserve.gov/",
                "https://data.federalreserve.gov/newsevents/pressreleases/monetary20250917a.htm",
                "https://www.federalreserve.gov/newsevents/pressreleases/monetary20250918a.htm"):
        with pytest.raises(ValueError):
            validate_official_url(url)
