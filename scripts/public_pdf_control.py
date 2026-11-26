"""Same public filing through two official hosts; no raw bodies or admission."""
from __future__ import annotations

import io
import json
from datetime import UTC, datetime

from pypdf import PdfReader

from investment_evidence_engine.official_pdf_transport import retrieve_pdf_bytes

URL = "https://www.sse.com.cn/disclosure/fund/announcement/c/new/2026-04-22/510050_20260422_5ENX.pdf"


MANAGER_URL = "https://www.chinaamc.com/upload/resources/file/2026/04/22/80979ea7b5804a56a022e75f69db3cd4.pdf"


def observe(url: str) -> dict:
    result = {"source_url": url, "observed_at": datetime.now(UTC).isoformat(),
              "research_only": True, "execution_allowed": False,
              "source_authenticity_independently_verified": False, "pit_verified": False,
              "raw_vendor_body_archived": False, "decision_authority": False}
    try:
        doc = retrieve_pdf_bytes(url)
    except Exception as exc:
        result.update(status="TRANSPORT_FAILED", error_type=type(exc).__name__)
        return result
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
    return result


def main() -> int:
    exchange = observe(URL)
    manager = observe(MANAGER_URL)
    for result in (exchange, manager):
        print("PUBLIC_PDF_CONTROL " + json.dumps(result, sort_keys=True))
    matched = all(r["status"] == "OBSERVED_PAGE_MATCH" for r in (exchange, manager))
    same_bytes = (exchange["bytes_sha256"] == manager["bytes_sha256"]
                  if "bytes_sha256" in exchange and "bytes_sha256" in manager else None)
    print("PUBLIC_PDF_PAIR " + json.dumps({"page_checks_both_pass": matched,
          "same_bytes": same_bytes, "independent_origin_proven": False,
          "decision_authority": False}, sort_keys=True))
    return 0 if matched else 2


if __name__ == "__main__":
    raise SystemExit(main())
