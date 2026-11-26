"""Fixed public positive cash-event control; no private case, forecast, or admission."""
from __future__ import annotations

import hashlib
import io
import json
import re
import unicodedata
from datetime import UTC, date, datetime
from decimal import Decimal
from importlib.metadata import version
from zoneinfo import ZoneInfo

from pypdf import PdfReader

from investment_evidence_engine.official_pdf_transport import retrieve_pdf_bytes

URL = "https://www.sse.com.cn/disclosure/fund/announcement/c/new/2026-11-25/510050_20261125_6HA6.pdf"
ANNOUNCED = date(2026, 11, 25)
RECORD = date(2026, 12, 1)
EX = date(2026, 12, 2)
PAY = date(2026, 12, 7)
AMOUNT_PER_TEN = Decimal("0.520")


def normalize(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).split())


def main() -> int:
    result = {
        "source_url": URL,
        "started_at": datetime.now(UTC).isoformat(),
        "private_data_included": False,
        "research_only": True,
        "decision_authority": False,
        "execution_allowed": False,
        "source_authenticity_independently_verified": False,
        "pit_verified": False,
        "earliest_available_at": None,
        "raw_vendor_body_archived": False,
        "payment_verified": False,
        "corporate_action_universe_verified": False,
    }
    try:
        doc = retrieve_pdf_bytes(URL)
        result.update(bytes_sha256=doc.sha256, bytes_length=len(doc.data),
                      retrieved_at=doc.retrieved_at)
        reader = PdfReader(io.BytesIO(doc.data), strict=True)
        if reader.is_encrypted or len(reader.pages) != 2:
            raise ValueError("unexpected fixed-control document structure")
        texts = [normalize(page.extract_text() or "") for page in reader.pages]
        result.update(page_count=len(texts), parser="pypdf", parser_version=version("pypdf"),
                      normalized_text_page_sha256=[
                          hashlib.sha256(text.encode("utf-8")).hexdigest() for text in texts])
        p1, p2 = texts
        # Exact labelled values on the two separately inspected source pages.
        # This is a fixed-document check, not a general ETF disclosure parser.
        checks = {
            "subject": bool(re.search(r"基金主代码[:：]?510050(?!\d)", p1)),
            "announcement_date": bool(re.search(r"公告送出日期[:：]?2026年11月25日", p1)),
            "amount_per_ten_units": bool(re.search(
                r"本次分红方案\(单位[:：]元/10份基金份额\)0\.520(?!\d)", p1)),
            "record_date": bool(re.search(r"权益登记日[:：]?2026年12月0?1日", p1)),
            "ex_date": bool(re.search(r"除息日[:：]?2026年12月0?2日", p1)),
            "pay_date": bool(re.search(r"现金红利发放日[:：]?2026年12月0?7日", p2)),
        }
        result["field_checks"] = checks
        if not all(checks.values()) or not ANNOUNCED <= RECORD < EX <= PAY:
            result["status"] = "FIELD_CHECK_MISMATCH"
        else:
            day = datetime.fromisoformat(doc.retrieved_at).astimezone(
                ZoneInfo("Asia/Shanghai")).date()
            # A scheduled event never proves that payment occurred.
            result.update(
                status="OBSERVED_SCHEDULED_CASH_EVENT",
                fund_code="510050",
                announcement_date=ANNOUNCED.isoformat(),
                record_date=RECORD.isoformat(),
                ex_date=EX.isoformat(),
                scheduled_pay_date=PAY.isoformat(),
                gross_cny_per_ten_units=str(AMOUNT_PER_TEN),
                gross_cny_per_unit=str(AMOUNT_PER_TEN / Decimal(10)),
                event_state=("ANNOUNCED_NOT_EFFECTIVE" if day < EX
                             else "SCHEDULED_DATE_REACHED_NOT_VERIFIED"),
                realized_cash_verified=False,
            )
    except Exception as exc:
        result.update(status="OBSERVATION_FAILED", error_type=type(exc).__name__)
    print("PUBLIC_CASH_EVENT " + json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result["status"] == "OBSERVED_SCHEDULED_CASH_EVENT" else 2


if __name__ == "__main__":
    raise SystemExit(main())
