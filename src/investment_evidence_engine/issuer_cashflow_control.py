"""Observed issuer full-report and mirror checks; no historical admission."""
from __future__ import annotations

import base64
import hashlib
import io
import re
import sys
from datetime import UTC, datetime
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

from .bounded_worker import run_json_worker, write_worker_result
from .issuer_revision_control import AMOUNT, extract_checked_rows, normalize_text
from .official_pdf_transport import MAX_PDF_BYTES, retrieve_pdf_bytes, validate_pdf_shape

EXCHANGE_ROOT = "https://disc.static.szse.cn/"
# Previously observed CNINFO original bytes and selected-page text digests,
# bound to run 45815738164 at 60e95df5a7a8a5a96f7e060ff8e26c13b9e96d34.
MIRRORS = {
    "annual_2024": {
        "path": "disc/disk03/finalpage/2025-04-28/39e26469-22ae-48d8-8b1c-a5ada42ea28d.PDF",
        "cninfo_day": "2025-04-29",
        "original_sha256": "6bf771249b13a1ada6b4dad2b7d57a0410a4381a00e48613e30239dde5305901",
        "page_sha256": "1cd63180378dca4fd428652a33c05a9cdd63cb7ded94dc270281d03afea1faf9",
    },
    "annual_2025": {
        "path": "disc/disk03/finalpage/2026-04-29/0f0fa13d-2576-40ee-89af-42616f09fa3e.PDF",
        "cninfo_day": "2026-04-29",
        "original_sha256": "f596cc168a69194f858fb680e7df5ccf518478cbbd6f7ffb99d85dcb66ac11d9",
        "page_sha256": "880706162fb3599bd3ecdee6b56acd2648dd5e127ba7d94367ef0a793111fd65",
    },
}
FULL_PATH = "download/disc/disk03/finalpage/2026-04-29/dd3d13e3-e035-4249-9d96-121b4121b417.PDF"
PATHS = {k: v["path"] for k, v in MIRRORS.items()} | {"full_2025": FULL_PATH}
Q1_PATH = "disc/disk03/finalpage/2026-04-29/e507872d-c0c2-407d-bc0e-828738560953.PDF"
# Visually checked consolidated statement pages 108-109 (not parent-only).
ROWS = {
    "ocf": (108, "经营活动产生的现金流量净额", ("653,089,056.43", "655,318,988.92")),
    "capex": (108, "购建固定资产、无形资产和其他长期资产支付的现金",
              ("1,570,291,924.55", "1,968,686,569.69")),
    "investing": (109, "投资活动产生的现金流量净额", ("-970,952,777.91", "-1,295,327,585.72")),
    "financing": (109, "筹资活动产生的现金流量净额", ("836,406,697.16", "578,374,702.92")),
    "borrowed": (109, "取得借款收到的现金", ("9,904,885,289.00", "7,650,746,810.70")),
    "repaid": (109, "偿还债务支付的现金", ("8,105,326,845.94", "6,245,324,105.42")),
    "cash_change": (109, "现金及现金等价物净增加额", ("517,171,048.68", "-65,663,650.56")),
    "fx_effect": (109, "汇率变动对现金及现金等价物的影响", ("-1,371,927.00", "-4,029,756.68")),
    "ending_cash": (109, "期末现金及现金等价物余额", ("782,255,256.65", "265,084,207.97")),
    "beginning_cash": (109, "期初现金及现金等价物余额", ("265,084,207.97", "330,747,858.53")),
}


def checked_cashflow(page108: str, page109: str) -> dict:
    first, second = normalize_text(page108), normalize_text(page109)
    if "合并现金流量表" not in first or "2025年度" not in first or "2024年度" not in first:
        raise ValueError("CASHFLOW_CONSOLIDATED_SCOPE")
    # Page 109 contains two statement scopes. Never read after parent header.
    if second.count("母公司现金流量表") != 1:
        raise ValueError("CASHFLOW_PARENT_SCOPE_BOUNDARY")
    second = second.split("母公司现金流量表", 1)[0]
    if "母公司现金流量表" in first:
        raise ValueError("CASHFLOW_CONSOLIDATED_SCOPE")
    values = {}
    for key, (page, label, expected) in ROWS.items():
        matches = re.findall(re.escape(label) + "(" + AMOUNT + ")(" + AMOUNT + ")",
                             first if page == 108 else second)
        if len(matches) != 1 or tuple(matches[0]) != expected:
            raise ValueError("CASHFLOW_ROW_OR_ORDER_MISMATCH")
        values[key] = tuple(Decimal(v.replace(",", "")) for v in matches[0])
    years = {}
    for i, year in enumerate(("2025", "2024")):
        row = {k: v[i] for k, v in values.items()}
        if row["ocf"] + row["investing"] + row["financing"] + row["fx_effect"] != row["cash_change"]:
            raise ValueError("CASHFLOW_CASH_CHANGE_NOT_RECONCILED")
        if row["beginning_cash"] + row["cash_change"] != row["ending_cash"]:
            raise ValueError("CASHFLOW_CASH_BALANCE_NOT_RECONCILED")
        row["operating_minus_capex_proxy"] = row["ocf"] - row["capex"]
        row["borrowed_minus_repaid_proxy"] = row["borrowed"] - row["repaid"]
        years[year] = {k: str(v) for k, v in row.items()}
    return {"years_cny": years, "cash_change_reconciled": True, "cash_balance_reconciled": True,
            "scope": "CONSOLIDATED_CASH_FLOW_STATEMENT_PAGES_108_109",
            "fcf_definition": "OPERATING_CASH_FLOW_MINUS_CASH_CAPEX_PROXY_NOT_FCFF_OR_FCFE",
            "actual_debt_balance_verified": False}


# Q1 is a same-declared-date counterexample to August-first revision inference.
Q1_ROWS = {
    "assets": (12, "资产总计", ("32,084,341,383.18", "32,067,826,798.82", "-16,514,584.36")),
    "liabilities": (14, "负债合计", ("20,996,249,839.64", "21,114,168,247.40", "117,918,407.76")),
    "parent_equity": (14, "归属于母公司所有者权益合计",
                      ("10,892,968,839.23", "10,758,535,847.11", "-134,432,992.12")),
    "total_equity": (14, "所有者权益合计", ("11,088,091,543.54", "10,953,658,551.42", "-134,432,992.12")),
}


def checked_q1_adjustments(page11: str, page12: str, page14: str) -> dict:
    pages = {11: normalize_text(page11), 12: normalize_text(page12), 14: normalize_text(page14)}
    if (any("中国天楹股份有限公司2026年第一季度报告" not in page for page in pages.values())
            or not all(mark in pages[11] for mark in ("2026年起首次执行新会计准则",
                "2025年12月31日", "2026年1月1日", "经审计", "未经审计", "调整数"))):
        raise ValueError("CASHFLOW_Q1_ADJUSTMENT_SCOPE")
    rows = {}
    for key, (page, label, expected) in Q1_ROWS.items():
        # "所有者权益合计" also occurs inside the preceding parent-equity label.
        prefix = r"(?<!归属于母公司)" if key == "total_equity" else ""
        cells = re.findall(prefix + re.escape(label) + "(" + AMOUNT + ")(" + AMOUNT + ")(" + AMOUNT + ")",
                           pages[page])
        if len(cells) != 1 or cells[0] != expected:
            raise ValueError("CASHFLOW_Q1_ROW_OR_ORDER")
        values = tuple(Decimal(v.replace(",", "")) for v in cells[0])
        if values[1] - values[0] != values[2]:
            raise ValueError("CASHFLOW_Q1_ADJUSTMENT_ARITHMETIC")
        rows[key] = values
    for index in range(3):
        if rows["assets"][index] != rows["liabilities"][index] + rows["total_equity"][index]:
            raise ValueError("CASHFLOW_Q1_BALANCE_NOT_RECONCILED")
    return {"rows_cny": {k: [str(v) for v in row] for k, row in rows.items()},
            "columns": ["2025-12-31_AUDITED", "2026-01-01_UNAUDITED", "ADJUSTMENT"],
            "balance_reconciled": True, "same_adjusted_values_as_half_2026": True,
            "declared_document_day": "2026-04-29", "same_day_order_verified": False,
            "first_availability_verified": False, "historical_vintage_verified": False}


def _child(kind: str, path: Path) -> None:
    started = datetime.now(UTC)
    doc = retrieve_pdf_bytes(EXCHANGE_ROOT + (Q1_PATH if kind == "q1_2026" else PATHS[kind]))
    write_worker_result(path, {"kind": kind, "url": doc.source_url, "sha256": doc.sha256,
                               "retrieved_at": doc.retrieved_at, "started_at": started.isoformat(),
                               "body": base64.b64encode(doc.data).decode("ascii")})


def observe(kind: str, folder: Path) -> dict:
    from pypdf import PdfReader

    url = EXCHANGE_ROOT + PATHS[kind]
    result = {"kind": kind, "url": url, "status": "BLOCK",
              "raw_body_retained": False, "historical_availability_verified": False,
              "decision_authority": False}
    task = run_json_worker((sys.executable, "-m", "investment_evidence_engine.issuer_cashflow_control",
                            "--child", kind), timeout_seconds=30, max_bytes=12 * 1024 * 1024)
    result |= {"worker_status": task.status, "elapsed_seconds": task.elapsed_seconds}
    if task.status != "OK" or task.payload is None:
        return result
    try:
        data = task.payload
        if (data["kind"], data["url"]) != (kind, url):
            raise ValueError("CASHFLOW_RECEIPT_IDENTITY")
        start, end = datetime.fromisoformat(data["started_at"]), datetime.fromisoformat(data["retrieved_at"])
        if start.utcoffset() is None or end.utcoffset() is None or not start <= end <= datetime.now(UTC):
            raise ValueError("CASHFLOW_RECEIPT_TIME")
        raw = base64.b64decode(data["body"], validate=True)
        validate_pdf_shape(raw, max_bytes=MAX_PDF_BYTES)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != data["sha256"]:
            raise ValueError("CASHFLOW_RECEIPT_HASH")
        target = folder / (digest + ".pdf")
        if not target.exists():
            with target.open("xb") as handle:
                handle.write(raw)
        reread = target.read_bytes()
        if reread != raw or hashlib.sha256(reread).hexdigest() != digest:
            raise ValueError("CASHFLOW_TEMPORARY_REHASH")
        result |= {"sha256": digest, "bytes": len(raw), "original_parent_rehash": "MATCH",
                   "temporary_file_rehash": "MATCH", "retrieved_at": end.isoformat(),
                   "started_at": start.isoformat(), "parser": "pypdf", "parser_version": version("pypdf")}
        reader = PdfReader(io.BytesIO(reread), strict=True)
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 500:
            raise ValueError("CASHFLOW_PAGE_COUNT_OR_ENCRYPTION")
        first = normalize_text(reader.pages[0].extract_text() or "")
        result["page_count"] = len(reader.pages)
        if "中国天楹股份有限公司" not in first:
            raise ValueError("CASHFLOW_DOCUMENT_IDENTITY")
        if kind == "q1_2026":
            if "2026年第一季度报告" not in first or "000035" not in first or len(reader.pages) != 14:
                raise ValueError("CASHFLOW_Q1_IDENTITY")
            texts = [normalize_text(reader.pages[i].extract_text() or "") for i in (10, 11, 13)]
            result["page_sha256"] = {str(i): hashlib.sha256(t.encode()).hexdigest()
                                     for i, t in zip((11, 12, 14), texts, strict=True)}
            result["q1_opening_adjustments"] = checked_q1_adjustments(*texts)
        elif kind == "full_2025":
            if "2025" not in first or "年度报告" not in first or len(reader.pages) < 109:
                raise ValueError("CASHFLOW_FULL_DOCUMENT_IDENTITY")
            texts = [normalize_text(reader.pages[i].extract_text() or "") for i in (107, 108)]
            if any("中国天楹股份有限公司" not in t for t in texts):
                raise ValueError("CASHFLOW_PAGE_IDENTITY")
            result["page_sha256"] = {str(i): hashlib.sha256(t.encode()).hexdigest()
                                     for i, t in zip((108, 109), texts, strict=True)}
            result["cashflow"] = checked_cashflow(*texts)
        else:
            if "000035" not in first or "年度报告摘要" not in first or len(reader.pages) < 3:
                raise ValueError("CASHFLOW_SUMMARY_IDENTITY")
            text = normalize_text(reader.pages[2].extract_text() or "")
            page_digest = hashlib.sha256(text.encode()).hexdigest()
            ref = MIRRORS[kind]
            result |= {"page": 3, "page_sha256": page_digest,
                       "cninfo_observed_run": 45815738164,
                       "cninfo_original_sha256": ref["original_sha256"],
                       "same_original_bytes": digest == ref["original_sha256"],
                       "same_checked_page_text": page_digest == ref["page_sha256"],
                       "cninfo_path_date": ref["cninfo_day"],
                       "szse_path_date": PATHS[kind].split("/")[-2],
                       "independent_origin_verified": False,
                       "historical_publication_clock_verified": False,
                       "table_rows_cny": extract_checked_rows(kind, text)}
    except Exception as exc:  # noqa: BLE001 - external parser boundary
        code = str(exc)
        return result | {"error_code": code if re.fullmatch(r"(?:ISSUER|CASHFLOW)_[A-Z0-9_]{1,90}", code)
                         else type(exc).__name__}
    return result | {"status": "OBSERVED"}


def main() -> dict:
    with TemporaryDirectory() as temp:
        receipts = [observe(kind, Path(temp)) for kind in PATHS]
        return {"status": "WARN" if all(r["status"] == "OBSERVED" for r in receipts) else "BLOCK",
                "documents": receipts, "pit_safe": False, "raw_body_retained": False,
                "execution_allowed": False, "decision_authority": False}


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "--child":
        raise SystemExit(2)
    _child(sys.argv[2], Path(sys.argv[3]))
