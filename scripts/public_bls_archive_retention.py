"""Fixed public-domain BLS statistical release; exact-byte retention transport."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import time
from datetime import UTC, date, datetime

import httpx
from pypdf import PdfReader
from public_payroll_vintage_control import bls_fields_from_text

from investment_evidence_engine.official_pdf_transport import read_bounded_pdf

URL = "https://fraser.stlouisfed.org/files/docs/releases/bls/bls_employnews_202508.pdf"
SHA = "d91f1329ce9e7a13c875cdaf56ebafd1cda360a13162800833c46888fa3d0516"
SIZE = 559888
RIGHTS = "https://www.bls.gov/opub/copyright-information.htm"


def validate_archive(raw: bytes) -> dict:
    if len(raw) != SIZE or hashlib.sha256(raw).hexdigest() != SHA:
        raise ValueError("ARCHIVE_VERSION_MISMATCH")
    reader = PdfReader(io.BytesIO(raw), strict=True)
    if reader.is_encrypted or len(reader.pages) != 40:
        raise ValueError("ARCHIVE_PAGE_SCOPE")
    fields = bls_fields_from_text(" ".join(reader.pages[i].extract_text() or "" for i in range(3)),
                                 date(2025, 9, 5), "AUGUST")
    if fields["august_change_jobs"] != 22000:
        raise ValueError("ARCHIVE_VALUE_MISMATCH")
    return fields | {"sha256": SHA, "bytes": SIZE, "page_count": 40}


def main():
    if os.environ["GITHUB_REPOSITORY"] != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("public repository required")
    with httpx.Client(timeout=6, follow_redirects=False) as client:
        with client.stream("GET", URL, headers={"Accept": "application/pdf",
                                                "Accept-Encoding": "identity"}) as response:
            raw = read_bounded_pdf(response, time.monotonic()+20)
    observed = datetime.now(UTC).isoformat()
    report = validate_archive(raw) | {"source_url": URL, "rights_policy_url": RIGHTS,
                "retrieved_at": observed, "executor_commit": os.environ["GITHUB_SHA"],
                "historical_capture_verified": False, "decision_authority": False,
                "status": "EXACT_PRIOR_DIGEST_MATCH"}
    print("BLS_ARCHIVE_RECEIPT " + json.dumps(report, sort_keys=True), flush=True)
    encoded = base64.b64encode(raw).decode("ascii")
    for i in range(0, len(encoded), 4096):
        print(f"BLS_ARCHIVE_BYTES {i//4096:04d} {encoded[i:i+4096]}", flush=True)
    print("BLS_ARCHIVE_END " + str(len(encoded)), flush=True)


if __name__ == "__main__":
    main()
