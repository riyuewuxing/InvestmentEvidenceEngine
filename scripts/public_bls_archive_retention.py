"""Fixed public-domain BLS statistical release; exact-byte retention transport."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import sys
import time
from datetime import UTC, date, datetime

import httpx
from public_payroll_vintage_control import bls_fields_from_text
from pypdf import PdfReader

from investment_evidence_engine.official_pdf_transport import read_bounded_pdf

URL = "https://fraser.stlouisfed.org/files/docs/releases/bls/bls_employnews_202508.pdf"
SHA = "d91f1329ce9e7a13c875cdaf56ebafd1cda360a13162800833c46888fa3d0516"
SIZE = 559888
RIGHTS = "https://www.bls.gov/opub/copyright-information.htm"


ARCHIVES = {
    "202508": (SHA, SIZE, 40, date(2025, 9, 5), "AUGUST", 22000),
    "202509": ("1a2e1d55c2a86ee7d471f957d2ffd0763a55beee95b0e2beb2106010475b46d7", 578129, 40,
               date(2025, 11, 20), "SEPTEMBER", -4000),
    "202511": ("6408e38172c272f3d8416f01873d3bc40d11c9ceb90933feb4939830cd63f6d2", 591295, 42,
               date(2025, 12, 16), "NOVEMBER", -26000),
}


def validate_archive(raw: bytes, month: str = "202508") -> dict:
    digest, size, pages, release, label, value = ARCHIVES[month]
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("ARCHIVE_VERSION_MISMATCH")
    reader = PdfReader(io.BytesIO(raw), strict=True)
    if reader.is_encrypted or len(reader.pages) != pages:
        raise ValueError("ARCHIVE_PAGE_SCOPE")
    fields = bls_fields_from_text(" ".join(reader.pages[i].extract_text() or "" for i in range(3)),
                                 release, label)
    if fields["august_change_jobs"] != value:
        raise ValueError("ARCHIVE_VALUE_MISMATCH")
    return fields | {"sha256": digest, "bytes": size, "page_count": pages}


def main():
    month = sys.argv[1] if len(sys.argv) == 2 else "202508"
    if month not in ARCHIVES or len(sys.argv) > 2:
        raise SystemExit("fixed archive month required")
    url = URL.replace("202508.pdf", month + ".pdf")
    if os.environ["GITHUB_REPOSITORY"] != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("public repository required")
    with httpx.Client(timeout=6, follow_redirects=False) as client:
        with client.stream("GET", url, headers={"Accept": "application/pdf",
                                                "Accept-Encoding": "identity"}) as response:
            raw = read_bounded_pdf(response, time.monotonic()+20)
    observed = datetime.now(UTC).isoformat()
    report = validate_archive(raw, month) | {"source_url": url, "archive_month": month, "rights_policy_url": RIGHTS,
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
