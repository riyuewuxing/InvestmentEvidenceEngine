import hashlib
import io
from pathlib import Path

import pytest
from pypdf import PdfWriter

from investment_evidence_engine import pdf_page_guard as guard
from investment_evidence_engine.bounded_worker import WorkerResult

BLS_SHA = "d91f1329ce9e7a13c875cdaf56ebafd1cda360a13162800833c46888fa3d0516"
BLS_PATH = Path(__file__).parents[1] / "public-evidence" / "sha256" / (BLS_SHA + ".pdf")


def synthetic_pdf(*, encrypted=False):
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_blank_page(width=100, height=100)
    if encrypted:
        writer.encrypt("fixture")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_actual_retained_public_domain_original_and_invalid_page():
    raw = BLS_PATH.read_bytes()
    count = guard.observe_pdf_page_count(raw, expected_sha256=BLS_SHA)
    assert count == 40
    guard.validate_page_span(actual_count=count, declared_count=40, page=39, page_end=40)
    with pytest.raises(ValueError, match="LOCATOR_OUT_OF_RANGE"):
        guard.validate_page_span(actual_count=count, declared_count=None, page=41)


def test_valid_pdf_measured_and_false_declared_count_rejected():
    raw = synthetic_pdf()
    count = guard.observe_pdf_page_count(raw, expected_sha256=hashlib.sha256(raw).hexdigest())
    assert count == 2
    guard.validate_page_span(actual_count=count, declared_count=None, page=2)
    with pytest.raises(ValueError, match="DECLARED_COUNT_MISMATCH"):
        guard.validate_page_span(actual_count=count, declared_count=999, page=2)


@pytest.mark.parametrize("raw", [b"%PDF-1.4\nsynthetic only\n%%EOF", synthetic_pdf(encrypted=True)])
def test_header_only_or_encrypted_bytes_cannot_be_formal_locator_source(raw):
    with pytest.raises(ValueError, match="PDF_PAGE_PARSE_BLOCK"):
        guard.observe_pdf_page_count(raw, expected_sha256=hashlib.sha256(raw).hexdigest())


@pytest.mark.parametrize(("page", "end"), [(0, None), (True, None), (2, 1), (1, 3), (1, True)])
def test_page_bounds_are_strict(page, end):
    with pytest.raises(ValueError, match="LOCATOR_OUT_OF_RANGE"):
        guard.validate_page_span(actual_count=2, declared_count=None, page=page, page_end=end)


def test_hash_mismatch_and_worker_failure(monkeypatch):
    raw = synthetic_pdf()
    digest = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError, match="BYTES_MISMATCH"):
        guard.observe_pdf_page_count(raw, expected_sha256="0" * 64)
    monkeypatch.setattr(guard, "run_json_worker", lambda *args, **kwargs: WorkerResult("WATCHDOG_TIMEOUT"))
    with pytest.raises(ValueError, match="PDF_PAGE_WORKER_WATCHDOG_TIMEOUT"):
        guard.observe_pdf_page_count(raw, expected_sha256=digest)


def test_wrong_worker_receipt_not_accepted(monkeypatch):
    raw = synthetic_pdf()
    digest = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(guard, "run_json_worker", lambda *args, **kwargs: WorkerResult("OK", {
        "status": "OBSERVED", "sha256": "0" * 64, "page_count": 2}))
    with pytest.raises(ValueError, match="RECEIPT_INVALID"):
        guard.observe_pdf_page_count(raw, expected_sha256=digest)
