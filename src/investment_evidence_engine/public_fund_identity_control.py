"""Fixed official product-identity/fee metadata observations; no trading admission.

Control cases are manually selected, not reconstructed vendor shortlist members.
Only document identifiers, dates and small factual metadata are emitted.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from .bounded_worker import run_json_worker, write_worker_result
from .official_pdf_transport import retrieve_pdf_bytes, validate_pdf_shape
from .public_symbol_change_control import compact

REPO = "riyuewuxing/InvestmentEvidenceEngine"
MAX_BYTES = 2 * 1024 * 1024
DOCS = {
    "510300": "https://www.sse.com.cn/disclosure/fund/announcement/c/new/2026-11-24/510300_20261124_2XJH.pdf",
    "161907": "https://static.cninfo.com.cn/finalpage/2025-11-05/1224785388.PDF",
    "013125": "https://static.cninfo.com.cn/finalpage/2025-06-30/1224031441.PDF",
}


def require(text: str, *terms: str) -> None:
    if not all(compact(term) in text for term in terms):
        raise ValueError("IDENTITY_REVIEWED_ANCHOR_MISSING")


def parse_summary(code: str, pages: tuple[str, ...]) -> dict:
    if code not in DOCS or not 3 <= len(pages) <= 8 or any(not isinstance(p, str) for p in pages):
        raise ValueError("IDENTITY_PAGE_SCOPE")
    first = compact(pages[0])
    strategy = compact(" ".join(pages[:3]))
    fees = compact(" ".join(pages[2:]))
    require(first, "基金产品资料概要", "产品概况", "基金代码" + code, "基金管理人", "基金经理")
    if code == "510300":
        require(first, "华泰柏瑞沪深300交易型开放式指数证券投资基金",
                "送出日期:2026年11月24日", "上海证券交易所", "2012年05月28日",
                "柳军", "2012年05月04日", "主要采取完全复制法")
        require(strategy, "业绩比较基准沪深300指数", "被动式投资策略",
                "年化跟踪误差控制在2%以内")
        require(fees, "管理费0.15%", "托管费0.05%", "基金运作综合费率(年化)0.20%")
        fields = {"product_kind": "INDEX_ETF", "share_class_codes": [code],
                  "document_day": "2026-11-24", "listed_exchange_reported": "SSE",
                  "listing_day_reported": "2012-05-28", "manager_name_reported": "柳军",
                  "manager_start_reported": "2012-05-04", "benchmark": "沪深300指数",
                  "management_rate_pct": "0.15", "custody_rate_pct": "0.05",
                  "fee_basis": "FUND_ASSET_NAV", "estimated_operation_rate_pct": {"510300": "0.20"},
                  "tracking_error_target_pct": "2", "target_not_realized_tracking_error": True}
    elif code == "161907":
        require(first, "万家中证红利交易型开放式指数证券投资基金联接基金",
                "送出日期:2025年11月05日", "下属基金交易代码161907", "下属基金交易代码015558",
                "基金中基金", "万家中证红利指数证券投资基金(LOF)",
                "2024年7月10日起", "杨坤")
        require(strategy, "目标ETF", "中证红利指数收益率×95%+银行活期存款利率(税后)×5%")
        require(fees, "管理费0.50%", "托管费0.10%",
                "目标ETF基金份额所对应资产净值不收取管理费和托管费",
                "持有期间0.61%", "持有期间0.71%")
        fields = {"product_kind": "ETF_FEEDER_FUND", "share_class_codes": ["161907", "015558"],
                  "document_day": "2025-11-05", "former_kind": "LOF",
                  "conversion_day_reported": "2024-07-10", "manager_name_reported": "杨坤",
                  "manager_start_reported": "2024-07-10",
                  "benchmark": "中证红利指数收益率95%+税后活期存款利率5%",
                  "management_rate_pct": "0.50", "custody_rate_pct": "0.10",
                  "fee_basis": "NAV_EXCLUDING_TARGET_ETF_ASSETS",
                  "estimated_operation_rate_pct": {"161907": "0.61", "015558": "0.71"},
                  "listing_and_channel_current_verified": False}
    else:
        require(first, "华夏中证细分食品饮料产业主题交易型开放式指数证券投资基金发起式联接基金",
                "送出日期:2025年6月30日", "下属基金代码013125",
                "基金中基金", "徐猛", "2021-10-26")
        require(strategy, "目标ETF", "中证细分食品饮料产业主题指数收益率×95%+人民币活期存款税后利率×5%")
        require(fees, "目标ETF份额所对应资产净值后剩余部分", "固定费率0.50%",
                "固定费率0.10%", "基金运作综合费率(年化)0.72%")
        fields = {"product_kind": "ETF_FEEDER_FUND", "share_class_codes": [code],
                  "document_day": "2025-06-30", "manager_name_reported": "徐猛",
                  "manager_start_reported": "2021-10-26",
                  "benchmark": "中证细分食品饮料产业主题指数收益率95%+人民币税后活期存款利率5%",
                  "management_rate_pct": "0.50", "custody_rate_pct": "0.10",
                  "fee_basis": "NAV_EXCLUDING_TARGET_ETF_ASSETS",
                  "estimated_operation_rate_pct": {code: "0.72"}}
    return fields | {"code": code, "current_notice_chain_verified": False,
                     "actual_cost_verified": False, "actual_dealing_verified": False,
                     "historical_first_availability_verified": False, "formal_admission": False,
                     "candidate_rank_membership_verified": False}


def child(code: str, path: Path) -> None:
    start = datetime.now(UTC)
    payload = {"code": code, "url": DOCS[code], "started_at": start.isoformat()}
    try:
        obs = retrieve_pdf_bytes(DOCS[code], max_bytes=MAX_BYTES)
        payload |= {"status": "OBSERVED", "body": base64.b64encode(obs.data).decode("ascii"),
                    "sha256": obs.sha256, "retrieved_at": obs.retrieved_at}
    except Exception as exc:
        payload |= {"status": "BLOCK", "error": type(exc).__name__}
    payload["finished_at"] = datetime.now(UTC).isoformat()
    write_worker_result(path, payload, max_bytes=3 * MAX_BYTES)


def observe(code: str) -> dict:
    start = datetime.now(UTC)
    worker = run_json_worker((sys.executable, "-m", "investment_evidence_engine.public_fund_identity_control",
                              "--child", code), timeout_seconds=35, max_bytes=3 * MAX_BYTES)
    result = {"code": code, "url": DOCS[code], "status": "BLOCK", "worker_status": worker.status,
              "elapsed_seconds": worker.elapsed_seconds, "raw_body_retained": False}
    if worker.status != "OK" or not isinstance(worker.payload, dict):
        return result
    p = worker.payload
    try:
        if (p["code"], p["url"]) != (code, DOCS[code]):
            raise ValueError("IDENTITY_RECEIPT_SCOPE")
        a, b = (datetime.fromisoformat(p[k]) for k in ("started_at", "finished_at"))
        if a.utcoffset() is None or b.utcoffset() is None or not start <= a <= b <= datetime.now(UTC):
            raise ValueError("IDENTITY_RECEIPT_CLOCK")
        result |= {"started_at": p["started_at"], "finished_at": p["finished_at"]}
        if p["status"] != "OBSERVED":
            return result | {"error": p.get("error", "CHILD_BLOCK")}
        captured = datetime.fromisoformat(p["retrieved_at"])
        if captured.utcoffset() is None or not a <= captured <= b:
            raise ValueError("IDENTITY_RECEIPT_CLOCK")
        raw = base64.b64decode(p["body"], validate=True)
        validate_pdf_shape(raw, max_bytes=MAX_BYTES)
        if hashlib.sha256(raw).hexdigest() != p["sha256"]:
            raise ValueError("IDENTITY_BYTE_HASH")
        result |= {"sha256": p["sha256"], "bytes": len(raw), "parent_rehash": "MATCH",
                   "retrieved_at": p["retrieved_at"]}
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw), strict=True)
        if reader.is_encrypted or not 3 <= len(reader.pages) <= 8:
            raise ValueError("IDENTITY_PAGE_SCOPE")
        pages = tuple(page.extract_text() or "" for page in reader.pages)
        result["page_count"] = len(pages)
        return result | {"status": "OBSERVED", "fields": parse_summary(code, pages)}
    except Exception as exc:
        message = str(exc)
        return result | {"error": message if re.fullmatch(r"[A-Z0-9_]{3,80}", message) else type(exc).__name__}


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    start = datetime.now(UTC)
    with ThreadPoolExecutor(max_workers=3) as pool:
        records = list(pool.map(observe, DOCS))
    complete = all(r["status"] == "OBSERVED" for r in records)
    report = {"status": "WARN" if complete else "BLOCK_PARTIAL",
              "executor_commit": os.environ["GITHUB_SHA"], "started_at": start.isoformat(),
              "finished_at": datetime.now(UTC).isoformat(), "records": records,
              "selection": "FIXED_PUBLIC_PRODUCT_IDENTITY_CONTROLS_NOT_VENDOR_RANK",
              "research_only": True, "formal_admission": False, "decision_authority": False,
              "execution_allowed": False}
    print("PUBLIC_FUND_IDENTITY " + json.dumps(report, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if complete else 2


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child" and sys.argv[2] in DOCS:
        child(sys.argv[2], Path(sys.argv[3]))
    elif len(sys.argv) == 1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
