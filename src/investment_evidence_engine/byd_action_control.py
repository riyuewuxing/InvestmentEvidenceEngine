"""Two fixed BYD issuer notices: cancellation versus distribution, not actual fills."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from .bounded_worker import run_json_worker, write_worker_result
from .issuer_revision_control import normalize_text
from .official_pdf_transport import retrieve_pdf_bytes

REPO = "riyuewuxing/InvestmentEvidenceEngine"
MODULE = "investment_evidence_engine.byd_action_control"
URLS = {
    "cancel": "https://static.cninfo.com.cn/finalpage/2024-05-14/1220039687.PDF",
    "distribution": "https://disc.static.szse.cn/disc/disk03/finalpage/2025-07-22/f30e6169-4779-487e-acff-8c1eff230fa4.PDF",
}


def require(text: str, markers: tuple[str, ...]) -> None:
    if not all(marker in text for marker in markers):
        raise ValueError("BYD_REVIEWED_FIELD_MISMATCH")


def parse_pages(kind: str, pages: list[str]) -> dict:
    pages = ["".join(normalize_text(t).split()) for t in pages]
    first = pages[0]
    if kind == "cancel":
        if len(pages) != 3:
            raise ValueError("BYD_PAGE_SCOPE")
        require(first, ("证券代码:002594", "2024-056", "比亚迪股份有限公司",
                        "关于2024年回购股份注销完成暨股份变动的公告"))
        require(pages[1], ("累计回购A股股份的数量为1,877,000股", "399,993,367元(不含交易费用)",
                           "注销日期为2024年5月10日", "2,911,142,855股减少至2,909,265,855股"))
        require(pages[2], ("及时办理工商变更登记", "比亚迪股份有限公司董事会", "2024年5月13日"))
        before, cancelled, after = 2911142855, 1877000, 2909265855
        if before - cancelled != after:
            raise ValueError("BYD_CANCEL_SHARE_MISMATCH")
        return {"event": "ISSUER_REPURCHASE_CANCELLATION", "before": before, "cancelled": cancelled,
                "after": after, "issuer_cash_spent_cny_excluding_fees": "399993367",
                "cancellation_date_reported": "2024-05-10", "document_date": "2024-05-13",
                "path_date": "2024-05-14", "registration_completion_verified": False,
                "shareholder_unit_multiplier_inferred": False, "cash_entitlement_inferred": False}
    if kind != "distribution" or len(pages) != 5:
        raise ValueError("BYD_PAGE_SCOPE")
    require(first, ("证券代码:002594", "2025-047", "比亚迪股份有限公司",
                    "2024年度利润分配及资本公积金转增股本实施公告",
                    "每10股派发现金红利人民币39.74元(含税)",
                    "每10股送红股8股", "每10股转增12股"))
    require(pages[1], ("每股按照面值1元人民币作为应纳税所得额",
                       "每10股合计应补缴税款人民币9.548元",
                       "每10股合计应补缴税款人民币4.774元"))
    require(pages[2], ("A股股权登记日为:2025年7月28日", "A股除权除息日为:2025年7月29日",
                       "A股新增可流通股份上市日:2025年7月29日",
                       "直接记入股东证券账户", "直接划入其资金账户"))
    require(pages[3], ("股份总数3,039,065,855100%6,078,131,7109,117,197,565100%",))
    require(pages[4], ("比亚迪股份有限公司董事会", "2025年7月21日"))
    before, added, after = 3039065855, 6078131710, 9117197565
    if before + added != after or 3 * before != after:
        raise ValueError("BYD_DISTRIBUTION_SHARE_MISMATCH")
    return {"event": "A_SHARE_COMBINED_DISTRIBUTION", "before": before, "added": added, "after": after,
            "document_date": "2025-07-21", "path_date": "2025-07-22", "record_date": "2025-07-28",
            "scheduled_ex_and_new_trading_date": "2025-07-29", "cash_per_old_share_cny": "3.974",
            "bonus_shares_per_ten": 8, "capital_transfer_shares_per_ten": 12,
            "old_share_entitlement_multiplier": 3, "taxable_bonus_face_value_per_old_share_cny": "0.8",
            "hypothetical_cash_and_share_examples": distribution_examples(),
            "actual_account_credit_verified": False, "historical_reference_price_verified": False,
            "h_share_terms_verified": False}


def distribution_examples() -> dict:
    # Exact integral lot scenario, not actual account balance or tax history.
    shares = 100
    gross = Decimal("3.974") * shares
    tax_base = (Decimal("3.974") + Decimal("0.8")) * shares
    return {"old_shares": shares, "new_shares": 3 * shares, "gross_cash_cny": str(gross),
            "conditional_tax_cny": {str(rate): str((tax_base * rate).quantize(Decimal(".01"), rounding=ROUND_HALF_UP))
                                     for rate in (Decimal("0"), Decimal("0.1"), Decimal("0.2"))},
            "actual_payment_verified": False}


def price_reference(prior: Decimal, close: Decimal, observed_previous_reference: Decimal) -> dict:
    """Fixed, conditional gross entitlement arithmetic for the reviewed A-share event."""
    if any(type(v) is not Decimal or not v.is_finite() or v <= 0 or v > 1000000
           for v in (prior, close, observed_previous_reference)) or prior <= Decimal("3.974"):
        raise ValueError("BYD_PRICE_REFERENCE_INVALID")
    reference = ((prior - Decimal("3.974")) / 3).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
    gross = (close * 3 + Decimal("3.974")) / prior - 1
    raw = close / prior - 1
    return {"prior_raw_close_cny": str(prior), "ex_day_raw_close_cny": str(close),
            "vendor_previous_reference_cny": str(observed_previous_reference),
            "conditional_cent_rounded_reference_cny": str(reference),
            "vendor_matches_conditional_reference": reference == observed_previous_reference,
            "raw_price_change_pct": str(raw * 100),
            "conditional_gross_wealth_change_pct": str(gross * 100),
            "actual_account_credit_verified": False, "official_reference_verified": False,
            "actual_tax_and_cost_verified": False, "historical_vintage_verified": False,
            "complete_action_history_verified": False, "pit_safe": False, "decision_authority": False}


def child(kind: str, target: Path, result: Path) -> None:
    from pypdf import PdfReader

    doc = retrieve_pdf_bytes(URLS[kind])
    target.write_bytes(doc.data)
    out = {"kind": kind, "url": doc.source_url, "source_bytes": len(doc.data),
           "source_sha256": doc.sha256, "observed_at": doc.retrieved_at, "status": "BLOCK"}
    try:
        reader = PdfReader(target, strict=True)
        if reader.is_encrypted or len(reader.pages) not in (3, 5):
            raise ValueError("BYD_PAGE_SCOPE")
        pages = [page.extract_text() or "" for page in reader.pages]
        out["page_count"] = len(pages)
        out["page_text_sha256"] = [hashlib.sha256(p.encode()).hexdigest() for p in pages]
        out["fields"] = parse_pages(kind, pages)
        out["status"] = "OBSERVED"
    except Exception as exc:
        out["error"] = str(exc)[:120] if isinstance(exc, ValueError) else type(exc).__name__
    write_worker_result(result, out)


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    observations = []
    for kind in URLS:
        with TemporaryDirectory() as folder:
            target = Path(folder) / "body.pdf"
            task = run_json_worker((sys.executable, "-m", MODULE, "--child", kind, str(target)),
                                   timeout_seconds=35, max_bytes=65536)
            row = task.payload or {"kind": kind, "status": "BLOCK"}
            row |= {"worker_status": task.status, "elapsed_seconds": task.elapsed_seconds}
            match = target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == row.get("source_sha256")
            row["parent_rehash"] = "MATCH" if match else "NOT_VERIFIED"
            if not match:
                row["status"] = "BLOCK"
            observations.append(row)
    status = "WARN" if all(r["status"] == "OBSERVED" for r in observations) else "BLOCK"
    report = {"status": status, "executor_commit": os.environ["GITHUB_SHA"], "observations": observations,
              "raw_source_retained": False, "historical_availability_verified": False, "pit_safe": False,
              "complete_action_history_verified": False, "decision_authority": False, "execution_allowed": False}
    print("PUBLIC_BYD_ACTION_CONTROL " + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    return 0 if status == "WARN" else 2


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--child" and sys.argv[2] in URLS:
        child(sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4]))
    elif len(sys.argv) == 1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
