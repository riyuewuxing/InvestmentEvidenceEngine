"""Observed Q3 disclosure and issuer-site mirror. No historical admission."""
from __future__ import annotations

import base64
import hashlib
import io
import re
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from .bounded_worker import run_json_worker, write_worker_result
from .issuer_disclosure_index import OBSERVED_ORG_ID, observe
from .issuer_revision_control import AMOUNT, normalize_text
from .official_pdf_transport import read_bounded_pdf, retrieve_pdf_bytes, validate_pdf_shape

ISSUER_PDF = "https://www.cnty.cn/uploads/files/202611/7018d6c15937f4e2a33a0d524b518bf2.pdf"
CNINFO_ROOT = "https://static.cninfo.com.cn/"
ROWS = {
    "revenue": ("营业收入", ("1,281,087,774.86", "1,365,493,364.57", "1,365,493,364.57",
                           "3,968,392,310.43", "3,942,265,178.09", "3,962,007,982.81")),
    "parent_profit": ("归属于上市公司股东的净利润", ("70,233,534.70", "101,803,192.08",
                        "93,924,290.08", "283,719,095.40", "313,347,692.85", "305,069,815.21")),
    "adjusted_profit": ("归属于上市公司股东的扣除非经常性损益的净利润",
                        ("68,131,313.27", "103,548,231.23", "95,669,329.23",
                         "297,826,123.82", "302,866,718.87", "294,588,841.23")),
}


def extract_q3(first: str, second: str) -> dict:
    first, second = normalize_text(first), normalize_text(second)
    if not all(s in first for s in ("中国天楹股份有限公司", "2026年第三季度报告",
                                    "000035", "TY2026-54", "会计政策变更", "调整前", "调整后")):
        raise ValueError("Q3_DOCUMENT_IDENTITY")
    result = {}
    pct = r"(-?[0-9]+[.][0-9]+)%"
    for key, (label, expected) in ROWS.items():
        group = "(" + AMOUNT + ")"
        pattern = re.escape(label) + r"\(元\)" + group * 3 + pct + group * 3 + pct
        match = re.findall(pattern, first)
        if len(match) != 1:
            raise ValueError("Q3_TABLE_ROW_MISSING")
        row = match[0]
        if row[:3] + row[4:7] != expected:
            raise ValueError("Q3_TABLE_VALUE_MISMATCH")
        v = [Decimal(x.replace(",", "")) for x in row[:3] + row[4:7]]
        q3_pct = ((v[0] / v[2] - 1) * 100).quantize(Decimal(".01"))
        ytd_pct = ((v[3] / v[5] - 1) * 100).quantize(Decimal(".01"))
        if q3_pct != Decimal(row[3]) or ytd_pct != Decimal(row[7]):
            raise ValueError("Q3_YOY_RECONCILIATION")
        result[key] = {
            "current_quarter": str(v[0]), "prior_quarter_original": str(v[1]),
            "prior_quarter_restated": str(v[2]), "quarter_yoy_pct": str(q3_pct),
            "current_ytd": str(v[3]), "prior_ytd_original": str(v[4]),
            "prior_ytd_restated": str(v[5]), "ytd_yoy_pct": str(ytd_pct),
            "ytd_yoy_using_original_pct": str(((v[3] / v[4] - 1)*100).quantize(Decimal(".01"))),
        }
    if not all(s in second for s in ("TY2026-22", "2026年1月1日", "调整前", "调整后")):
        raise ValueError("Q3_POLICY_LINK")
    return {"rows_cny": result, "comparative_basis": "RESTATED_AS_DISCLOSED_IN_Q3",
            "historical_vintage_verified": False, "decision_authority": False}


def _child(url: str, path: Path) -> None:
    if url == ISSUER_PDF:
        import time

        import httpx

        # Fixed issuer link observed on official investor-relations page.
        # No expansion of the general official-source URL policy.
        with httpx.Client(timeout=5.0, follow_redirects=False) as client:
            with client.stream("GET", url, headers={"Accept-Encoding": "identity",
                                                     "Accept": "application/pdf"}) as response:
                raw = read_bounded_pdf(response, time.monotonic()+20)
        captured = datetime.now(UTC).isoformat()
    else:
        doc = retrieve_pdf_bytes(url)
        if doc.source_url != url:
            raise ValueError("Q3_URL_CHANGED")
        raw, captured = doc.data, doc.retrieved_at
    write_worker_result(path, {"url": url, "sha256": hashlib.sha256(raw).hexdigest(),
                               "body": base64.b64encode(raw).decode(), "retrieved_at": captured})


def observe_pdf(url: str, folder: Path, *, pressure: bool = False) -> dict:
    from pypdf import PdfReader

    out = {"url": url, "status": "BLOCK", "raw_body_retained": False}
    # CNINFO must be an exact static path, not a generic network target.
    if url != ISSUER_PDF and not re.fullmatch(
            re.escape(CNINFO_ROOT) + r"finalpage/2026-[0-9]{2}-[0-9]{2}/[0-9]{1,24}\.PDF", url):
        return out | {"error": "Q3_URL_SCOPE"}
    started = datetime.now(UTC)
    task = run_json_worker((sys.executable, "-m", "investment_evidence_engine.issuer_q3_control",
                            "--child", url), timeout_seconds=30, max_bytes=12*1024*1024)
    out |= {"worker_status": task.status, "elapsed_seconds": task.elapsed_seconds}
    if task.status != "OK" or task.payload is None:
        return out
    try:
        p = task.payload
        captured = datetime.fromisoformat(p["retrieved_at"])
        if p["url"] != url or captured.utcoffset() is None or not started <= captured <= datetime.now(UTC):
            raise ValueError("Q3_RECEIPT_IDENTITY")
        raw = base64.b64decode(p["body"], validate=True)
        validate_pdf_shape(raw)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != p["sha256"]:
            raise ValueError("Q3_BYTE_HASH")
        target = folder / (digest + ".pdf")
        if not target.exists():
            target.write_bytes(raw)
        reopened = target.read_bytes()
        if reopened != raw or hashlib.sha256(reopened).hexdigest() != digest:
            raise ValueError("Q3_REOPEN_HASH")
        out |= {"sha256": digest, "bytes": len(raw), "retrieved_at": captured.isoformat(),
                "parent_and_temporary_rehash": "MATCH"}
        reader = PdfReader(io.BytesIO(reopened), strict=True)
        if reader.is_encrypted or len(reader.pages) != 12:
            raise ValueError("Q3_PAGE_SCOPE")
        pages = [normalize_text(reader.pages[i].extract_text() or "") for i in (0, 1)]
        out |= {"page_count": len(reader.pages),
                "page_sha256": [hashlib.sha256(x.encode()).hexdigest() for x in pages],
                "financial": extract_q3(*pages)}
        if pressure:
            from .issuer_q3_pressure import EXPECTED_SHA, extract_pressure

            if digest != EXPECTED_SHA:
                raise ValueError("Q3_PRESSURE_VERSION_MISMATCH")
            out["pressure"] = extract_pressure({i: reader.pages[i-1].extract_text() or ""
                                               for i in (5, 6, 7, 9, 10)})
    except Exception as exc:  # noqa: BLE001
        message = str(exc)
        return out | {"error": message if re.fullmatch(r"Q3_[A-Z_]+", message) else type(exc).__name__}
    return out | {"status": "OBSERVED"}


def run_control() -> dict:
    index, _ = observe("q3", OBSERVED_ORG_ID)
    report = {"index": index, "status": "BLOCK", "decision_authority": False, "pit_safe": False,
              "historical_availability_verified": False, "revision_universe_complete": False}
    with TemporaryDirectory() as temp:
        folder = Path(temp)
        # Fixed official issuer mirror is independent of index availability.
        issuer = observe_pdf(ISSUER_PDF, folder)
        report["issuer"] = issuer
        candidates = index.get("candidates", [])
        if index["status"] != "OBSERVED" or len(candidates) != 1:
            return report | {"blocker": "Q3_INDEX_UNIQUE_CANDIDATE_NOT_ESTABLISHED"}
        primary = observe_pdf(CNINFO_ROOT + candidates[0]["attachment"], folder)
        report["cninfo"] = primary
        if primary["status"] != "OBSERVED" or issuer["status"] != "OBSERVED":
            return report | {"blocker": "Q3_TWO_ROUTE_OBSERVATION_INCOMPLETE"}
        report["same_original_bytes"] = primary["sha256"] == issuer["sha256"]
        report["same_financial_values"] = primary["financial"] == issuer["financial"]
        if not report["same_financial_values"]:
            return report | {"blocker": "Q3_FINANCIAL_CONFLICT"}
        return report | {"status": "WARN", "independent_origin_verified": False}


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "--child":
        raise SystemExit(2)
    _child(sys.argv[2], Path(sys.argv[3]))
