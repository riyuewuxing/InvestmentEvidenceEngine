from __future__ import annotations

import hashlib
import io
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree

from .resilience import RetryPolicy, retry_call


@dataclass(frozen=True)
class OfficialSourceSpec:
    source_id: str
    url: str
    expected_tokens: tuple[str, ...] = ()
    fallback_urls: tuple[str, ...] = ()


@dataclass(frozen=True)
class FetchedOfficialSource:
    url: str
    text: str
    content_sha256: str
    content_type: str


DEFAULT_OFFICIAL_SOURCES: dict[str, OfficialSourceSpec] = {
    "SSE_TRADING_RULES_2026": OfficialSourceSpec(
        source_id="SSE_TRADING_RULES_2026",
        # SSE can intermittently reject GitHub-hosted runner IPs. Keep independent official
        # representations across attachment/page/category/mirror/technical-document routes so a
        # single CDN policy does not masquerade as rule unavailability. Every resolved document
        # still has to contain the expected rule identity tokens below.
        url="https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/10816492/files/704204728fe74fff89de4f16efda4791.docx",
        fallback_urls=(
            "https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml",
            "https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml",
            "https://www.sse.com.cn/lawandrules/sselawsrules2025/fund/trading/c/c_20260424_10817739.shtml",
            "https://big5.sse.com.cn/site/cht/www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml",
            "https://star.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20260424_10816474.shtml",
            "https://www.sse.com.cn/services/tradingtech/development/c/10816505/files/8006a51174524e7cae832568b5e726a6.pdf",
        ),
        expected_tokens=("上海证券交易所交易规则", "2026年修订"),
    ),
    "SZSE_TRADING_RULES_2026": OfficialSourceSpec(
        source_id="SZSE_TRADING_RULES_2026",
        url="https://docs.static.szse.cn/www/lawrules/rule/trade/current/W020260424690713155663.pdf",
        fallback_urls=(
            "https://www.szse.cn/lawrules/rule/allrules/bussiness/t20260424_620190.html",
        ),
        expected_tokens=("深圳证券交易所交易规则", "2026年修订"),
    ),
    "CSRC_PUBLIC_FUND_OPERATION_RULES": OfficialSourceSpec(
        source_id="CSRC_PUBLIC_FUND_OPERATION_RULES",
        url="https://www.csrc.gov.cn/csrc/c106256/c1653978/content.shtml",
        fallback_urls=(
            "https://www.csrc.gov.cn/csrc/c101877/c1029566/content.shtml",
            "https://www.csrc.gov.cn/csrc/c106256/c1653978/1653978/files/1b26d5810f794a629581888ace061d08.pdf",
        ),
        expected_tokens=("公开募集证券投资基金运作管理办法",),
    ),
}

_ALLOWED_HOST_SUFFIXES = (
    "sse.com.cn",
    "szse.cn",
    "csrc.gov.cn",
    "cninfo.com.cn",
)
_OFFICIAL_RETRY_POLICY = RetryPolicy(attempts=3, base_delay_seconds=0.5, max_delay_seconds=2.0)
_RETRYABLE_HTTP_STATUS = {408, 425, 429, 500, 502, 503, 504}


def validate_official_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("official source URL must be HTTPS")
    host = parsed.hostname.lower()
    if not any(host == suffix or host.endswith("." + suffix) for suffix in _ALLOWED_HOST_SUFFIXES):
        raise ValueError(f"official source host is not allowlisted: {host}")
    return url


def _docx_text(body: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        xml = archive.read("word/document.xml")
    root = ElementTree.fromstring(xml)
    texts = [node.text or "" for node in root.iter() if node.tag.endswith("}t")]
    return "".join(texts)


def _pdf_text(body: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf is required for official PDF validation") from exc
    reader = PdfReader(io.BytesIO(body))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _decode_body(body: bytes, *, url: str, content_type: str) -> str:
    lowered_url = url.lower()
    lowered_type = content_type.lower()
    if lowered_url.endswith(".docx") or "wordprocessingml" in lowered_type:
        return _docx_text(body)
    if lowered_url.endswith(".pdf") or "application/pdf" in lowered_type:
        return _pdf_text(body)
    charset = "utf-8"
    match = re.search(r"charset=([\w-]+)", lowered_type)
    if match:
        charset = match.group(1)
    try:
        return body.decode(charset, errors="ignore")
    except LookupError:
        return body.decode("utf-8", errors="ignore")


def fetch_official_url(url: str, timeout: float = 20.0) -> FetchedOfficialSource:
    validate_official_url(url)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/128 Safari/537.36 InvestmentEvidenceEngine/0.1",
            "Accept": "text/html,application/xhtml+xml,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read(8_000_000)
        content_type = str(response.headers.get("Content-Type") or "application/octet-stream")
    return FetchedOfficialSource(
        url=url,
        text=_decode_body(body, url=url, content_type=content_type),
        content_sha256=hashlib.sha256(body).hexdigest(),
        content_type=content_type,
    )


def _retryable_official_exception(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in _RETRYABLE_HTTP_STATUS
    return isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError))


def fetch_official_spec(
    spec: OfficialSourceSpec,
    timeout: float = 20.0,
) -> tuple[FetchedOfficialSource, list[str]]:
    failures: list[str] = []
    for url in (spec.url, *spec.fallback_urls):
        try:
            fetched, retry_failures = retry_call(
                lambda: fetch_official_url(url, timeout=timeout),
                policy=_OFFICIAL_RETRY_POLICY,
                retry_if=_retryable_official_exception,
            )
            failures.extend(f"{url}::RETRY_RECOVERED::{item}" for item in retry_failures)
            return fetched, failures
        except Exception as exc:  # noqa: BLE001 - resilient official-source boundary
            failures.append(f"{url}::{type(exc).__name__}:{exc}")
    raise RuntimeError("all official source URLs failed: " + " | ".join(failures))


def fetch_text(url: str, timeout: float = 20.0) -> str:
    """Backward-compatible helper used by older bootstrap code."""
    return fetch_official_url(url, timeout=timeout).text


def normalized_document_text(text: str) -> str:
    return "".join(text.split()).replace(" ", "")
