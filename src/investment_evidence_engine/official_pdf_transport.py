"""Bounded exact-route PDF byte retrieval; no semantic or publication admission."""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .official_pdf_routes import canonical_official_pdf_url

MAX_PDF_BYTES = 8 * 1024 * 1024
MAX_WALL_SECONDS = 20.0


@dataclass(frozen=True)
class PdfByteObservation:
    source_url: str
    data: bytes
    retrieved_at: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


def validate_pdf_shape(data: bytes, *, max_bytes: int = MAX_PDF_BYTES) -> None:
    """Only transport structure; not a parser or source authenticity proof."""
    if len(data) > max_bytes:
        raise ValueError("Official PDF exceeds allowed size")
    if not data.startswith(b"%PDF-") or not data.rstrip(b"\x00\t\n\f\r ").endswith(b"%%EOF"):
        raise ValueError("Response is not a complete PDF")


def read_bounded_pdf(response: Any, deadline: float, *, max_bytes: int = MAX_PDF_BYTES) -> bytes:
    if response.status_code != 200:
        raise ValueError(f"Official PDF retrieval returned HTTP {response.status_code}")
    length = response.headers.get("content-length")
    if length is not None and (not length.isascii() or not length.isdecimal() or int(length) > max_bytes):
        raise ValueError("Official PDF exceeds allowed size")
    encoding = response.headers.get("content-encoding", "identity").lower()
    if encoding not in {"", "identity"}:
        raise ValueError("Encoded response is not allowed")
    if response.headers.get("content-range") is not None:
        raise ValueError("Partial response is not allowed")
    if time.monotonic() > deadline:
        raise TimeoutError("Official PDF deadline exceeded")
    data = bytearray()
    for chunk in response.iter_raw(chunk_size=65536):
        if time.monotonic() > deadline:
            raise TimeoutError("Official PDF deadline exceeded")
        if len(data) + len(chunk) > max_bytes:
            raise ValueError("Official PDF exceeds allowed size")
        data.extend(chunk)
    if length is not None and len(data) != int(length):
        raise ValueError("Incomplete official PDF response")
    if time.monotonic() > deadline:
        raise TimeoutError("Official PDF deadline exceeded")
    raw = bytes(data)
    validate_pdf_shape(raw, max_bytes=max_bytes)
    return raw


def retrieve_pdf_bytes(url: str, *, max_bytes: int = MAX_PDF_BYTES,
                       transport: Any = None) -> PdfByteObservation:
    """Exact canonical route; no redirect, retry, compression or raw body log.

    Per-operation network timeout plus monotonic body checks are not an OS-level
    hard deadline. A caller requiring that guarantee must use a process watchdog.
    An optional httpx transport is used for deterministic synthetic tests.
    """
    import httpx

    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 0 < max_bytes <= MAX_PDF_BYTES:
        raise ValueError("invalid PDF byte limit")
    canonical = canonical_official_pdf_url(url)
    deadline = time.monotonic() + MAX_WALL_SECONDS
    with httpx.Client(timeout=httpx.Timeout(5.0), follow_redirects=False, trust_env=True,
                      transport=transport) as client:
        with client.stream("GET", canonical, headers={
            "Accept": "application/pdf",
            "Accept-Encoding": "identity",
        }) as response:
            data = read_bounded_pdf(response, deadline, max_bytes=max_bytes)
    return PdfByteObservation(canonical, data, datetime.now(UTC).isoformat())
