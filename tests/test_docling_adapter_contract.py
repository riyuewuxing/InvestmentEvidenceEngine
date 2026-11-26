from pathlib import Path

import pytest
from pydantic import ValidationError

from investment_evidence_engine.docling_adapter import (
    DOCLING_RUNTIME_PDF_OCR_ENABLED,
    DOCLING_RUNTIME_PDF_PIPELINE,
    DOCLING_RUNTIME_TABLE_STRUCTURE_ENABLED,
    DOCLING_UPSTREAM_COMMIT,
    DOCLING_VERSION,
    DoclingParseRequest,
    sha256_bytes,
    verify_source,
)

FIXTURE = Path("fixtures/docling_native/sample_filing.html")
FIXTURE_SHA256 = "7f32fbc09eda502bb0a8d0191218873a1202e245378c8e0563b7728b1db939cb"


def test_docling_pin_is_exact() -> None:
    assert DOCLING_VERSION == "2.150.1"
    assert DOCLING_UPSTREAM_COMMIT == "5e600e8d37a11f70b62f795ea1e3ce3a4052e551"


def test_runtime_pdf_profile_is_model_free_native_text_transform_only() -> None:
    assert DOCLING_RUNTIME_PDF_PIPELINE == "NATIVE_MODEL_FREE"
    assert DOCLING_RUNTIME_PDF_OCR_ENABLED is False
    assert DOCLING_RUNTIME_TABLE_STRUCTURE_ENABLED is False


def test_fixture_hash_is_stable() -> None:
    assert sha256_bytes(FIXTURE.read_bytes()) == FIXTURE_SHA256
    request = DoclingParseRequest(
        source_path=str(FIXTURE),
        expected_source_sha256=FIXTURE_SHA256,
    )
    path, observed = verify_source(request)
    assert path == FIXTURE
    assert observed == FIXTURE_SHA256


def test_remote_input_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DoclingParseRequest(
            source_path="https://example.com/report.pdf",
            expected_source_sha256="0" * 64,
        )


def test_network_enable_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DoclingParseRequest(
            source_path=str(FIXTURE),
            expected_source_sha256=FIXTURE_SHA256,
            allow_network=True,
        )


def test_wrong_source_hash_fails_closed() -> None:
    request = DoclingParseRequest(
        source_path=str(FIXTURE),
        expected_source_sha256="0" * 64,
    )
    with pytest.raises(ValueError, match="source SHA256 mismatch"):
        verify_source(request)
