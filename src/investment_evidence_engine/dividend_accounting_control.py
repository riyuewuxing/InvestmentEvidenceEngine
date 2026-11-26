"""Fixed issuer financial-statement/approval observation.

Amounts in a dividend announcement, retained earnings, a payable balance,
and a shareholder bank credit are different measures. Never derive a payment
or a per-share entitlement from the accounting balances.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import sys
from datetime import UTC, date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from tempfile import TemporaryDirectory

from .bounded_worker import run_json_worker, write_worker_result
from .issuer_cashflow_control import EXCHANGE_ROOT, FULL_PATH
from .issuer_revision_control import ROOT, normalize_text
from .official_pdf_transport import MAX_PDF_BYTES, retrieve_pdf_bytes, validate_pdf_shape

REPO = "riyuewuxing/InvestmentEvidenceEngine"
PRIOR_ANNUAL_SHA = "8a4b4c31599c17aaefc440721c0ccb6752456dd334ed03b7af24df4a35eed99d"
DOCS = {
    "approval_2025": (ROOT+"2025-06-11/1223836050.PDF", (1, 4), "2024年年度股东大会决议公告"),
    "approval_2026": (ROOT+"2026-06-25/1225386239.PDF", (1, 3, 4), "2025年年度股东会决议公告"),
    "half_2025": (ROOT+"2025-08-22/1224535903.PDF", (1, 63, 157), "2025年半年度报告"),
    "annual_2025": (EXCHANGE_ROOT+FULL_PATH, (1, 112), "2025年年度报告"),
    "half_2026": (ROOT+"2026-08-29/1225528853.PDF", (1, 66, 68, 151, 159), "2026年半年度报告"),
}


def _require(text: str, *markers: str) -> None:
    if not all(normalize_text(v) in text for v in markers):
        raise ValueError("DIVIDEND_REVIEWED_FIELDS_MISMATCH")


def _row(text: str, label: str, expected: tuple[str, ...]) -> list[str]:
    # Fixed visually reviewed row. No global search for an amount from a
    # different table or period. Spaces within amounts removed by normalization.
    amount = r"(-?[0-9]{1,3}(?:,[0-9]{3})+\.[0-9]{2})"
    matches = re.findall(re.escape(normalize_text(label))+amount*len(expected), text)
    if len(matches) != 1:
        raise ValueError("DIVIDEND_ROW_MISSING_OR_DUPLICATE")
    cells = (matches[0],) if len(expected) == 1 else matches[0]
    if tuple(cells) != expected:
        raise ValueError("DIVIDEND_ROW_VALUE_OR_ORDER")
    return [str(Decimal(v.replace(",", ""))) for v in cells]


def parse_pages(kind: str, pages: dict[int, str]) -> dict:
    _, wanted, title = DOCS[kind]
    if set(pages) != set(wanted):
        raise ValueError("DIVIDEND_PAGE_SCOPE")
    pages = {p: normalize_text(t) for p, t in pages.items()}
    _require(pages[1], "中国天楹股份有限公司", title)
    if kind.startswith("approval"):
        y = int(kind[-4:])
        _require(pages[1], "证券代码:000035", "TY2025-22" if y == 2025 else "TY2026-28")
        if y == 2025:
            _require(pages[1], "2025年6月10日", "910,998,698股")
            body = pages[4]
            anchor = "5、审议并通过了《关于公司2024年度利润分配预案的议案》"
            next_anchor = "6、审议并通过了"
            vote = (907417360, 3100738, 480600)
            electorate = 910998698
            pct = "99.6069"
            result_text = "表决结果:本次股东大会审议通过了上述议案"
        else:
            # Attendance may cross the first-page boundary, so use the
            # exact share total and meeting date on the first page.
            _require(pages[1], "2026年6月24日", "804,180,120股")
            body = pages[3]+pages[4]
            anchor = "4、审议并通过了《关于公司2025年度利润分配预案的议案》"
            next_anchor = "5、审议并通过了"
            vote = (801288620, 2757500, 134000)
            electorate = 804180120
            pct = "99.6404"
            result_text = "表决结果:本次股东会审议通过了上述议案"
        if body.count(anchor) != 1:
            raise ValueError("DIVIDEND_RESOLUTION_IDENTITY")
        section = body.split(anchor, 1)[1].split(next_anchor, 1)[0]
        _require(section, "总表决情况:同意"+f"{vote[0]:,}"+"股", pct+"%",
                 "反对"+f"{vote[1]:,}"+"股", "弃权"+f"{vote[2]:,}"+"股", result_text)
        if sum(vote) != electorate or (Decimal(vote[0])*100/Decimal(electorate)).quantize(
                Decimal(".0001"), rounding=ROUND_HALF_UP) != Decimal(pct):
            raise ValueError("DIVIDEND_VOTE_RECONCILIATION")
        return {"profit_year": y-1, "meeting_day": f"{y}-06-"+("10" if y == 2025 else "24"),
                "document_day": f"{y}-06-"+("11" if y == 2025 else "25"),
                "votes_for_against_abstained": list(vote), "votes_present": electorate,
                "approval_pct": pct, "approved": True, "entitlement_record_date_verified_here": False,
                "actual_payment_verified": False}
    for p in wanted[1:]:
        _require(pages[p], "中国天楹股份有限公司", title)
    # For each report, identify the visually reviewed table row and verify
    # separate parent-distribution and minority-interest columns.
    label = "3.对所有者(或股东)的分配"
    if kind == "annual_2025":
        row = _row(pages[112], label, ("-84,058,749.07", "-84,058,749.07",
                                     "-20,419,710.44", "-104,478,459.51"))
        return {"period_end": "2025-12-31", "document_day": "2026-04-29",
                "parent_distribution_cny": str(-Decimal(row[0])),
                "minority_distribution_cny": str(-Decimal(row[2])),
                "total_consolidated_distribution_cny": str(-Decimal(row[3]))}
    if kind == "half_2025":
        row = _row(pages[63], label, ("-84,058,749.04", "-84,058,749.04",
                                    "-16,745,050.47", "-100,803,799.51"))
        _require(pages[157], "(2)应付股利", "期末余额", "期初余额")
        bal = _row(pages[157], "普通股股利", ("108,340,447.03", "12,936,647.52"))
        return {"period_end": "2025-06-30", "document_day": "2025-08-22",
                "parent_distribution_cny": str(-Decimal(row[0])),
                "minority_distribution_cny": str(-Decimal(row[2])),
                "total_consolidated_distribution_cny": str(-Decimal(row[3])),
                "reported_ordinary_dividend_payable_current_prior_cny": bal,
                "payable_scope": "2025_REPORT_LABEL_ORDINARY_DIVIDENDS_NOT_EVENT_SPECIFIC"}
    row = _row(pages[66], label, ("-85,969,179.68", "-85,969,179.68",
                                "-12,600,000.00", "-98,569,179.68"))
    prior = _row(pages[68], label, ("-84,058,749.04", "-84,058,749.04",
                                  "-16,745,050.47", "-100,803,799.51"))
    _require(pages[151], "(2)应付股利", "期末余额", "期初余额")
    # This balance sheet note has a blank prior-year cell for ordinary shares.
    balance = _row(pages[151], "普通股股利", ("85,969,179.68",))
    _require(pages[159], "58、未分配利润", "本期", "上期")
    earnings = _row(pages[159], "应付普通股股利", ("85,969,179.68", "84,058,749.04"))
    if -Decimal(row[0]) != Decimal(balance[0]) or earnings != [str(-Decimal(row[0])), str(-Decimal(prior[0]))]:
        raise ValueError("DIVIDEND_H1_TABLE_CONFLICT")
    return {"period_end": "2026-06-30", "document_day": "2026-08-29",
            "parent_distribution_cny": str(-Decimal(row[0])),
            "minority_distribution_cny": str(-Decimal(row[2])),
            "total_consolidated_distribution_cny": str(-Decimal(row[3])),
            "comparative_2025_h1_parent_distribution_cny": str(-Decimal(prior[0])),
            "reported_ordinary_dividend_payable_cny": balance[0],
            "prior_cell_status": "BLANK_NOT_IMPUTED_ZERO",
            "retained_earnings_current_prior_dividend_cny": earnings}


def reconcile(receipts: list[dict], declared: dict[str, str]) -> dict:
    if (len(receipts) != len(DOCS) or {x["kind"] for x in receipts} != set(DOCS)
            or any(x["status"] != "OBSERVED" for x in receipts)):
        raise ValueError("DIVIDEND_INCOMPLETE_OBSERVATION")
    fields = {x["kind"]: x["fields"] for x in receipts}
    for kind in ("half_2025", "annual_2025", "half_2026"):
        f = fields[kind]
        if Decimal(f["parent_distribution_cny"])+Decimal(f["minority_distribution_cny"]) != Decimal(
                f["total_consolidated_distribution_cny"]):
            raise ValueError("DIVIDEND_EQUITY_COLUMN_RECONCILIATION")
    half25 = Decimal(fields["half_2025"]["parent_distribution_cny"])
    full25 = Decimal(fields["annual_2025"]["parent_distribution_cny"])
    half26 = Decimal(fields["half_2026"]["parent_distribution_cny"])
    comparative = Decimal(fields["half_2026"]["comparative_2025_h1_parent_distribution_cny"])
    if half25 != comparative:
        raise ValueError("DIVIDEND_COMPARATIVE_MISMATCH")
    return {"declared_implementation_total_cny": declared,
            "2025_h1_accounting_distribution_cny": str(half25),
            "2025_full_year_accounting_distribution_cny": str(full25),
            "2025_h1_repeated_in_2026_comparative": str(comparative),
            "2025_implementation_minus_h1_accounting_cny": str(Decimal(declared["2025"])-half25),
            "2025_implementation_minus_annual_accounting_cny": str(Decimal(declared["2025"])-full25),
            "2025_annual_minus_h1_cny": str(full25-half25),
            "2026_h1_accounting_distribution_cny": str(half26),
            "2026_implementation_minus_h1_accounting_cny": str(Decimal(declared["2026"])-half26),
            "amount_difference_cause_verified": False, "shareholder_bank_credit_verified": False,
            "event_specific_cash_paid_verified": False, "historical_availability_verified": False,
            "accounting_period_end_is_not_payment_date": True,
            "scope": "ISSUER_REPORTED_ACCOUNTING_AND_DECLARED_DISTRIBUTION_NOT_SETTLEMENT"}


def child(kind: str, target: Path) -> None:
    started = datetime.now(UTC)
    doc = retrieve_pdf_bytes(DOCS[kind][0])
    write_worker_result(target, {"kind": kind, "url": doc.source_url,
        "started_at": started.isoformat(), "retrieved_at": doc.retrieved_at,
        "sha256": doc.sha256, "body": base64.b64encode(doc.data).decode("ascii")})


def observe(kind: str, folder: Path) -> dict:
    from pypdf import PdfReader

    url, wanted, _ = DOCS[kind]
    result = {"kind": kind, "url": url, "status": "BLOCK", "raw_body_retained": False,
              "historical_availability_verified": False}
    task = run_json_worker((sys.executable, "-m", __name__ if __name__ != "__main__" else
                           "investment_evidence_engine.dividend_accounting_control", "--child", kind),
                           timeout_seconds=30, max_bytes=12*1024*1024)
    result |= {"worker_status": task.status, "elapsed_seconds": task.elapsed_seconds}
    if task.status != "OK" or task.payload is None:
        return result
    try:
        p = task.payload
        if (p["kind"], p["url"]) != (kind, url):
            raise ValueError("DIVIDEND_SOURCE_IDENTITY")
        start, end = (datetime.fromisoformat(p[k]) for k in ("started_at", "retrieved_at"))
        if start.utcoffset() is None or end.utcoffset() is None or not start <= end <= datetime.now(UTC):
            raise ValueError("DIVIDEND_SOURCE_TIME")
        raw = base64.b64decode(p["body"], validate=True)
        validate_pdf_shape(raw, max_bytes=MAX_PDF_BYTES)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != p["sha256"]:
            raise ValueError("DIVIDEND_SOURCE_HASH")
        target = folder/(kind+".pdf")
        with target.open("xb") as f:
            f.write(raw)
        reread = target.read_bytes()
        if reread != raw or hashlib.sha256(reread).hexdigest() != digest:
            raise ValueError("DIVIDEND_TEMPORARY_REHASH")
        result |= {"source_sha256": digest, "source_bytes": len(raw), "parent_rehash": "MATCH",
                   "temporary_rehash": "MATCH", "started_at": start.isoformat(), "retrieved_at": end.isoformat()}
        if kind == "annual_2025" and digest != PRIOR_ANNUAL_SHA:
            raise ValueError("DIVIDEND_PRIOR_ANNUAL_VERSION_MISMATCH")
        reader = PdfReader(io.BytesIO(reread), strict=True)
        if reader.is_encrypted or not max(wanted) <= len(reader.pages) <= 500:
            raise ValueError("DIVIDEND_PAGE_COUNT")
        texts = {i: reader.pages[i-1].extract_text() or "" for i in wanted}
        result |= {"page_count": len(reader.pages), "page_text_sha256": {
            str(i): hashlib.sha256(normalize_text(t).encode()).hexdigest() for i, t in texts.items()}}
        result["fields"] = parse_pages(kind, texts)
    except Exception as exc:  # noqa: BLE001 - untrusted document parser boundary.
        code = str(exc)
        return result | {"error_code": code if re.fullmatch(r"DIVIDEND_[A-Z_]+", code) else type(exc).__name__}
    return result | {"status": "OBSERVED"}


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    with TemporaryDirectory() as temp:
        results = [observe(k, Path(temp)) for k in DOCS]
    report = {"executor_commit": os.environ["GITHUB_SHA"], "status": "BLOCK", "subject": "000035",
              "documents": results, "decision_authority": False, "execution_allowed": False,
              "historical_availability_verified": False}
    try:
        # Prior observed public issuer receipts #45856529066 and #45856977986.
        report["reconciliation"] = reconcile(results, {"2025": "84058753.47", "2026": "85969179.68"})
        report["status"] = "WARN"
    except (ValueError, KeyError, TypeError) as exc:
        report["blocker"] = str(exc)
    print("PUBLIC_DIVIDEND_ACCOUNTING " + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    return 0 if report["status"] == "WARN" else 2


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child" and sys.argv[2] in DOCS:
        child(sys.argv[2], Path(sys.argv[3]))
    elif len(sys.argv) == 1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
