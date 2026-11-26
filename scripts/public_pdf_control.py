"""One fixed public control; only transport metadata and page-check booleans."""
from __future__ import annotations

import io
import json
from datetime import UTC, datetime

from pypdf import PdfReader

from investment_evidence_engine.official_pdf_transport import retrieve_pdf_bytes

URL = "https://www.sse.com.cn/disclosure/fund/announcement/c/new/2026-04-22/510050_20260422_5ENX.pdf"


def main() -> int:
    result = {"source_url": URL, "observed_at": datetime.now(UTC).isoformat(),
              "research_only": True, "execution_allowed": False,
              "source_authenticity_independently_verified": False, "pit_verified": False,
              "raw_vendor_body_archived": False, "decision_authority": False}
    try:
        doc = retrieve_pdf_bytes(URL)
    except Exception as exc:
        result.update(status="TRANSPORT_FAILED", error_type=type(exc).__name__)
        print("PUBLIC_PDF_CONTROL " + json.dumps(result, sort_keys=True))
        return 2
    result.update(bytes_sha256=doc.sha256, bytes_length=len(doc.data), retrieved_at=doc.retrieved_at)
    try:
        reader = PdfReader(io.BytesIO(doc.data), strict=True)
        if reader.is_encrypted or not 3 <= len(reader.pages) <= 100:
            raise ValueError("control page count or encryption")
        text = "".join((reader.pages[2].extract_text() or "").split())
        # Fixed independently inspected PDF page 3. Not semantic source admission.
        checks = {"fund_code": "510050" in text, "net_asset": "66,731,248,686.19" in text,
                  "unit_nav": "2.8985" in text}
        result.update(page_count=len(reader.pages), checked_pdf_page=3, page_checks=checks,
                      status="OBSERVED_PAGE_MATCH" if all(checks.values()) else "PAGE_CHECK_MISMATCH")
    except Exception as exc:
        result.update(status="PARSE_FAILED", error_type=type(exc).__name__)
    print("PUBLIC_PDF_CONTROL " + json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "OBSERVED_PAGE_MATCH" else 2


if __name__ == "__main__":
    raise SystemExit(main())
