"""Verify a reviewed locator against the actual retained PDF page tree.

No extraction, publication/PIT proof, source authentication or semantic
claim admission. Page parsing runs in a bounded direct child and uses only
a temporary copy of already observed bytes; no network or body logging.
"""
from __future__ import annotations

import hashlib
import io
import re
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from .bounded_worker import run_json_worker, write_worker_result
from .official_pdf_transport import MAX_PDF_BYTES, validate_pdf_shape

MAX_REVIEW_PAGES = 1000
PAGE_TIMEOUT_SECONDS = 12.0


def _raw_digest(raw: bytes, expected_sha256: str) -> str:
    if (not isinstance(raw, bytes) or not isinstance(expected_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None):
        raise ValueError("PDF_PAGE_INPUT")
    validate_pdf_shape(raw)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected_sha256:
        raise ValueError("PDF_PAGE_BYTES_MISMATCH")
    return digest


def _count_pages(raw: bytes) -> int:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(raw), strict=True)
    if reader.is_encrypted:
        raise ValueError("PDF_PAGE_ENCRYPTED")
    pages = reader.pages
    count = len(pages)
    if not 1 <= count <= MAX_REVIEW_PAGES:
        raise ValueError("PDF_PAGE_COUNT_LIMIT")
    identities = set()
    for page in pages:
        ref = page.indirect_reference
        if page.get("/Type") != "/Page" or ref is None:
            raise ValueError("PDF_PAGE_TREE_INVALID")
        identity = (ref.idnum, ref.generation)
        if identity in identities:
            raise ValueError("PDF_PAGE_TREE_DUPLICATE")
        identities.add(identity)
    if len(identities) != count:
        raise ValueError("PDF_PAGE_TREE_COUNT_MISMATCH")
    return count


def _child(input_path: Path, expected: str, output: Path) -> None:
    try:
        if input_path.is_symlink() or not input_path.is_file():
            raise ValueError("PDF_PAGE_INPUT")
        with input_path.open("rb") as handle:
            raw = handle.read(MAX_PDF_BYTES + 1)
        digest = _raw_digest(raw, expected)
        count = _count_pages(raw)
        payload = {"status": "OBSERVED", "sha256": digest, "page_count": count}
    except Exception as exc:
        reason = str(exc)
        payload = {"status": "BLOCK", "error": reason if re.fullmatch(
            r"PDF_PAGE_[A-Z_]+", reason) else type(exc).__name__}
    write_worker_result(output, payload, max_bytes=4096)


def observe_pdf_page_count(raw: bytes, *, expected_sha256: str) -> int:
    """Return a measured count only after the child rehashes the actual bytes."""
    digest = _raw_digest(raw, expected_sha256)
    with TemporaryDirectory(prefix="reviewed-pdf-pages-") as folder:
        path = Path(folder) / "original.pdf"
        with path.open("xb") as handle:
            handle.write(raw)
        # Called as an imported library in both consumers; the module entry
        # point only executes the child, never recursively launches itself.
        worker = run_json_worker((sys.executable, "-m", __name__, "--child",
                                  str(path), digest), timeout_seconds=PAGE_TIMEOUT_SECONDS,
                                 max_bytes=4096)
    if worker.status != "OK" or not isinstance(worker.payload, dict):
        raise ValueError("PDF_PAGE_WORKER_" + worker.status)
    payload = worker.payload
    if payload.get("status") != "OBSERVED":
        raise ValueError("PDF_PAGE_PARSE_BLOCK")
    count = payload.get("page_count")
    if (set(payload) != {"status", "sha256", "page_count"} or payload.get("sha256") != digest
            or type(count) is not int or not 1 <= count <= MAX_REVIEW_PAGES):
        raise ValueError("PDF_PAGE_RECEIPT_INVALID")
    return count


def validate_page_span(*, actual_count: int, declared_count: int | None,
                       page: int, page_end: int | None = None) -> None:
    """An absent declared count never exempts a locator from the actual bound."""
    if type(actual_count) is not int or not 1 <= actual_count <= MAX_REVIEW_PAGES:
        raise ValueError("PDF_PAGE_COUNT_INVALID")
    if declared_count is not None and (type(declared_count) is not int or declared_count != actual_count):
        raise ValueError("PDF_PAGE_DECLARED_COUNT_MISMATCH")
    end = page if page_end is None else page_end
    if type(page) is not int or type(end) is not int or not 1 <= page <= end <= actual_count:
        raise ValueError("PDF_PAGE_LOCATOR_OUT_OF_RANGE")


if __name__ == "__main__":
    if len(sys.argv) != 5 or sys.argv[1] != "--child":
        raise SystemExit(2)
    _child(Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4]))
