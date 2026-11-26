import hashlib
import time

import httpx
import pytest

from investment_evidence_engine.official_pdf_transport import (
    read_bounded_pdf,
    retrieve_pdf_bytes,
    validate_pdf_shape,
)

URL = "https://www.sse.com.cn/disclosure/fund/announcement/c/new/2026-04-22/510050_20260422_TEST.pdf"
RAW = b"%PDF-1.4\nfixture\n%%EOF\n"


class Stream(httpx.SyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks

    def __iter__(self):
        yield from self.chunks


def test_exact_bytes_and_request_contract():
    calls = []

    def handle(req):
        calls.append(str(req.url))
        assert req.headers["accept-encoding"] == "identity"
        return httpx.Response(200, headers={"content-length": str(len(RAW))},
                              stream=Stream([RAW[:4], RAW[4:]]))

    doc = retrieve_pdf_bytes(URL, transport=httpx.MockTransport(handle))
    assert doc.data == RAW and doc.sha256 == hashlib.sha256(RAW).hexdigest()
    assert doc.source_url == URL and calls == [URL]


def test_redirect_is_never_followed():
    calls = []

    def handle(req):
        calls.append(str(req.url))
        return httpx.Response(302, headers={"location": "https://evil.example/report.pdf"})

    with pytest.raises(ValueError, match="HTTP 302"):
        retrieve_pdf_bytes(URL, transport=httpx.MockTransport(handle))
    assert calls == [URL]


@pytest.mark.parametrize(("headers", "chunks"), [
    ({"content-encoding": "gzip"}, [RAW]),
    ({"content-range": "bytes 0-10/50"}, [RAW]),
    ({"content-length": "99"}, [RAW]),
    ({"content-length": "not-a-number"}, [RAW]),
    ({}, [b"not a PDF"]),
    ({}, [RAW+b"trailing non-PDF junk"]),
    ({}, [RAW[:-6]]),
])
def test_bad_transport_never_returns_observation(headers, chunks):
    def handle(req):
        return httpx.Response(200, headers=headers, stream=Stream(chunks))

    with pytest.raises(ValueError):
        retrieve_pdf_bytes(URL, transport=httpx.MockTransport(handle))


def test_size_and_deadline_even_for_missing_length():
    with pytest.raises(ValueError, match="size"):
        retrieve_pdf_bytes(URL, max_bytes=8, transport=httpx.MockTransport(
            lambda req: httpx.Response(200, stream=Stream([RAW]))))
    with pytest.raises(TimeoutError):
        read_bounded_pdf(httpx.Response(200, stream=Stream([RAW])), time.monotonic()-1)
    with pytest.raises(ValueError):
        validate_pdf_shape(RAW, max_bytes=8)
