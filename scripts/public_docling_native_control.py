"""A bounded public native-PDF fixture control; never a private runtime-admission gate."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from investment_evidence_engine.docling_adapter import (
    DOCLING_UPSTREAM_COMMIT,
    DOCLING_VERSION,
    DoclingParseRequest,
    parse_local_document,
)

FIXTURE = Path("fixtures/docling_native/sample_filing.pdf.b64")
EXPECTED_SHA = "fe26735389e0618b3af1657035eb5c916d27da950d6c5d18da72f163b90a04df"
MARKERS = ["Round3 Docling PDF Fixture", "Revenue", "Net Income", "Risk Notice"]


@contextmanager
def deny_python_network():
    original_connect = socket.socket.connect
    original_create_connection = socket.create_connection

    def blocked(*args, **kwargs):
        raise RuntimeError("PUBLIC_NATIVE_PDF_NETWORK_BLOCKED")

    socket.socket.connect = blocked
    socket.create_connection = blocked
    try:
        yield
    finally:
        socket.socket.connect = original_connect
        socket.create_connection = original_create_connection


def main() -> int:
    result = {
        "status": "BLOCK",
        "observed_at": datetime.now(UTC).isoformat(),
        "public_commit": os.environ.get("GITHUB_SHA"),
        "scope": "PUBLIC_SYNTHETIC_NATIVE_PDF_TRANSFORM_ONLY",
        "private_data_included": False,
        "private_dual_gate_verified": False,
        "decision_authority": False,
        "execution_allowed": False,
        "os_network_isolation_verified": False,
    }
    try:
        raw = base64.b64decode(b"".join(FIXTURE.read_bytes().split()), validate=True)
        sha = hashlib.sha256(raw).hexdigest()
        if sha != EXPECTED_SHA:
            raise ValueError("FIXTURE_SHA_MISMATCH")
        result.update(fixture_sha256=sha, fixture_bytes=len(raw))
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "fixture.pdf"
            path.write_bytes(raw)
            with deny_python_network():
                blocked = False
                try:
                    socket.create_connection(("127.0.0.1", 9), timeout=0.1)
                except RuntimeError as exc:
                    blocked = str(exc) == "PUBLIC_NATIVE_PDF_NETWORK_BLOCKED"
                if not blocked:
                    raise RuntimeError("NETWORK_GUARD_CHECK_FAILED")
                parsed = parse_local_document(
                    DoclingParseRequest(source_path=str(path), expected_source_sha256=sha),
                    expected_markers=MARKERS,
                )
            expected_output_sha = hashlib.sha256(parsed.markdown.encode("utf-8")).hexdigest()
            if (parsed.status != "PASS" or parsed.source_sha256 != sha
                    or parsed.markdown_sha256 != expected_output_sha
                    or parsed.parser_version != DOCLING_VERSION
                    or parsed.upstream_commit != DOCLING_UPSTREAM_COMMIT
                    or parsed.markers_found != MARKERS):
                raise ValueError("TRANSFORM_CONTRACT_MISMATCH")
            result.update(
                status="PASS",
                python_network_guard_checked=True,
                parser=parsed.parser,
                parser_version=parsed.parser_version,
                upstream_commit=parsed.upstream_commit,
                parsed_markdown_sha256=expected_output_sha,
                marker_count=len(parsed.markers_found),
                marker_names=parsed.markers_found,
                parser_warnings=parsed.warnings,
            )
    except Exception as exc:
        result.update(error_type=type(exc).__name__, error_message=str(exc)[:300])
    print("PUBLIC_DOCLING_CONTROL " + json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
