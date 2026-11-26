from __future__ import annotations

import hashlib
import importlib.metadata
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

# Runtime admission intentionally installs the slim distribution with only the model-free PDF
# parser extra. The import package remains `docling`; using the slim distribution avoids pulling
# the local-model dependency stack (including accelerate) that the admitted NativePdfPipeline
# neither needs nor is allowed to claim.
DOCLING_PACKAGE = "docling-slim"
DOCLING_VERSION = "2.150.1"
DOCLING_UPSTREAM_COMMIT = "5e600e8d37a11f70b62f795ea1e3ce3a4052e551"
DOCLING_RUNTIME_PDF_PIPELINE = "NATIVE_MODEL_FREE"
DOCLING_RUNTIME_PDF_OCR_ENABLED = False
DOCLING_RUNTIME_TABLE_STRUCTURE_ENABLED = False


class DoclingParseRequest(BaseModel):
    source_path: str
    expected_source_sha256: str
    allow_network: bool = False

    @model_validator(mode="after")
    def local_only(self) -> DoclingParseRequest:
        lowered = self.source_path.lower()
        if lowered.startswith(("http://", "https://")):
            raise ValueError("Docling runtime admission accepts local fixture bytes only")
        if self.allow_network:
            raise ValueError("Docling runtime admission fixture must run with network disabled")
        return self


class DoclingParseResult(BaseModel):
    status: str
    parser: str
    parser_version: str
    upstream_commit: str
    source_path: str
    source_sha256: str
    markdown: str
    markdown_sha256: str
    markers_found: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def verify_source(request: DoclingParseRequest) -> tuple[Path, str]:
    path = Path(request.source_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    observed = sha256_bytes(path.read_bytes())
    if observed != request.expected_source_sha256:
        raise ValueError(
            f"source SHA256 mismatch: expected={request.expected_source_sha256} observed={observed}"
        )
    return path, observed


def installed_docling_version() -> str:
    return importlib.metadata.version(DOCLING_PACKAGE)


def _document_converter_for(source_path: Path):
    """Build the narrow converter used by the admitted local transform.

    For PDFs this intentionally uses Docling's official model-free NativePdfPipeline, backed by
    docling-parse. It extracts native PDF text/cells and embedded bitmaps without layout, OCR, or
    table models, so a cold air-gapped runtime does not need to fetch model artifacts. This narrow
    contract does not claim scanned-PDF OCR, semantic layout reconstruction, table extraction,
    XBRL parsing, or source-locator fidelity; each requires separate fixtures before routing.
    """

    from docling.document_converter import DocumentConverter

    if source_path.suffix.lower() != ".pdf":
        return DocumentConverter()

    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import NativePdfPipelineOptions
    from docling.document_converter import NativePdfFormatOption

    pipeline_options = NativePdfPipelineOptions()
    pipeline_options.generate_page_images = False
    pipeline_options.generate_picture_images = False
    return DocumentConverter(
        allowed_formats=[InputFormat.PDF],
        format_options={
            InputFormat.PDF: NativePdfFormatOption(pipeline_options=pipeline_options),
        },
    )


def parse_local_document(
    request: DoclingParseRequest,
    *,
    expected_markers: list[str] | None = None,
) -> DoclingParseResult:
    source_path, source_sha = verify_source(request)

    installed = installed_docling_version()
    if installed != DOCLING_VERSION:
        raise RuntimeError(
            f"Docling version must be exactly {DOCLING_VERSION}; installed={installed}"
        )

    converter = _document_converter_for(source_path)
    result = converter.convert(source_path)
    markdown = result.document.export_to_markdown()
    markdown_sha = sha256_bytes(markdown.encode("utf-8"))

    markers = expected_markers or []
    found = [marker for marker in markers if marker in markdown]
    missing = [marker for marker in markers if marker not in markdown]
    if missing:
        raise ValueError(f"Docling fixture output is missing expected markers: {missing}")

    warnings = []
    if source_path.suffix.lower() == ".pdf":
        warnings.append(
            "runtime admission covers only Docling NativePdfPipeline native-text transform; "
            "OCR, semantic layout, PDF tables, XBRL and source-locator fidelity require separate evidence"
        )

    return DoclingParseResult(
        status="PASS",
        parser="docling-native-pdf",
        parser_version=installed,
        upstream_commit=DOCLING_UPSTREAM_COMMIT,
        source_path=str(source_path),
        source_sha256=source_sha,
        markdown=markdown,
        markdown_sha256=markdown_sha,
        markers_found=found,
        warnings=warnings,
    )
