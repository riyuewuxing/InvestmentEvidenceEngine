"""Fixed official fund dealing notices: distinct primary/secondary channels.

These are current observations of old announcements, not archived historical
availability, full dealing schedules or actual order acceptance.
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
from decimal import Decimal
from pathlib import Path

from .bounded_worker import run_json_worker, write_worker_result
from .official_pdf_transport import retrieve_pdf_bytes, validate_pdf_shape
from .public_symbol_change_control import compact

REPO = "riyuewuxing/InvestmentEvidenceEngine"
MAX_BYTES = 2 * 1024 * 1024
DOCS = {
    "holiday": ("2026-09-03/1225543819.PDF", "159607"),
    "halt": ("2026-08-28/1225518347.PDF", "159696"),
    "cap": ("2026-08-10/1225463572.PDF", "161907"),
    "earlier_release": ("2026-05-18/1225310600.PDF", "161907"),
}


def url_for(key: str) -> str:
    return "https://static.cninfo.com.cn/finalpage/" + DOCS[key][0]


def require(text: str, *terms: str) -> None:
    if not all(compact(term) in text for term in terms):
        raise ValueError("FUND_DEALING_REVIEWED_ANCHORS")


def parse_notice(key: str, pages: tuple[str, ...]) -> dict:
    if key not in DOCS or not 1 <= len(pages) <= 5 or any(not isinstance(p, str) for p in pages):
        raise ValueError("FUND_DEALING_PAGE_SCOPE")
    first = compact(pages[0])
    full = compact(" ".join(pages))
    if key == "holiday":
        require(first, "嘉实中证海外中国互联网30交易型开放式指数证券投资基金(QDII)",
                "基金主代码159607", "嘉实基金管理有限公司", "公告送出日期:2026年9月3日",
                "暂停申购起始日2026年9月7日", "暂停赎回起始日2026年9月7日",
                "2026年9月7日纽约证券交易所、纳斯达克证券交易所休市",
                "恢复申购日2026年9月8日", "恢复赎回日2026年9月8日")
        require(full, "投资者在2026年9月7日仍可进行本基金的二级市场交易",
                "2026年9月8日起(含2026年9月8日)恢复本基金的日常申购、赎回业务")
        fields = {"symbol": "159607", "declared_day": "2026-09-03",
                  "effective_session": "2026-09-07", "planned_resume_session": "2026-09-08",
                  "primary_subscription": "SUSPENDED", "primary_redemption": "SUSPENDED",
                  "secondary_trading": "REPORTED_ALLOWED", "actual_resume_verified": False}
    elif key == "halt":
        require(first, "易方达纳斯达克100交易型开放式指数证券投资基金(QDII)",
                "基金代码:159696", "二级市场交易价格溢价风险提示及停复牌公告",
                "2026年8月27日", "收盘价为2.044元",
                "收盘时基金份额参考净值(IOPV)为1.8392元",
                "2026年8月28日开市起停牌", "2026年8月28日10:30起复牌",
                "停牌期间本基金赎回业务照常办理", "实际申赎状态请以最新公告为准")
        require(full, "易方达基金管理有限公司", "2026年8月28日")
        price, iopv = Decimal("2.044"), Decimal("1.8392")
        fields = {"symbol": "159696", "declared_day": "2026-08-28",
                  "reference_session": "2026-08-27", "reported_close_cny": str(price),
                  "reported_close_iopv_cny": str(iopv),
                  "reported_close_iopv_premium_pct": str((price / iopv - 1) * 100),
                  "effective_session": "2026-08-28", "halt_start_label": "MARKET_OPEN",
                  "planned_resume_local": "10:30", "local_timezone": "Asia/Shanghai",
                  "secondary_trading_during_halt": "SUSPENDED",
                  "primary_redemption_during_halt": "REPORTED_ALLOWED",
                  "primary_subscription_during_halt": "UNKNOWN", "actual_resume_verified": False,
                  "independent_iopv_verified": False}
    else:
        require(first, "万家中证红利交易型开放式指数证券投资基金联接基金",
                "基金主代码161907", "万家基金管理有限公司",
                "下属分级基金的交易代码161907015558")
        if key == "cap":
            require(first, "公告送出日期:2026年8月10日",
                    "暂停大额申购(含转换转入、定期定额投资)起始日2026年8月11日",
                    "该分级基金暂停大额申购(含转换转入、定期定额投资)金额100万元100万元")
            require(full, "A类及C类份额单日申购金额合并计算不超过100万元",
                    "所有销售机构(包括代销及直销渠道)", "单日单个基金账户单笔或多笔累计",
                    "限额为100万元(不含100万元)", "对超过100万元部分的申请基金管理人有权拒绝",
                    "赎回及转换转出等业务正常办理", "具体时间将另行公告")
            fields = {"fund_main_code": "161907", "share_class_codes": ["161907", "015558"],
                      "declared_day": "2026-08-10", "effective_session": "2026-08-11",
                      "subscription_state": "LIMITED", "reported_cap_cny": "1000000",
                      "cap_scope": "ONE_FUND_ACCOUNT_PER_DAY_COMBINED_CLASSES_ALL_CHANNELS",
                      "cap_operations": ["SUBSCRIBE", "CONVERT_IN", "PERIODIC_INVESTMENT"],
                      "at_exact_cap": "AMBIGUOUS_SOURCE_WORDING", "above_cap": "REJECTION_POSSIBLE",
                      "redemption": "REPORTED_ALLOWED", "convert_out": "REPORTED_ALLOWED",
                      "resume_session": None}
        else:
            require(first, "公告送出日期:2026年5月18日",
                    "恢复大额申购(含转换转入、定期定额投资)起始日2026年5月18日")
            require(full, "取消对本基金单日单个基金账户单笔或多笔累计金额100万元以上的大额申购",
                    "限制")
            fields = {"fund_main_code": "161907", "share_class_codes": ["161907", "015558"],
                      "declared_day": "2026-05-18", "effective_session": "2026-05-18",
                      "specific_previous_cap_removed": True,
                      "all_other_limits_absent_verified": False}
    return fields | {"historical_first_availability_verified": False,
                     "complete_notice_chain_verified": False,
                     "actual_acceptance_verified": False, "decision_authority": False}


def _child(key: str, path: Path) -> None:
    started = datetime.now(UTC)
    payload = {"key": key, "url": url_for(key), "started_at": started.isoformat()}
    try:
        obs = retrieve_pdf_bytes(url_for(key), max_bytes=MAX_BYTES)
        payload |= {"status": "OBSERVED", "body": base64.b64encode(obs.data).decode("ascii"),
                    "sha256": obs.sha256, "retrieved_at": obs.retrieved_at}
    except Exception as exc:
        payload |= {"status": "BLOCK", "error": type(exc).__name__}
    payload["finished_at"] = datetime.now(UTC).isoformat()
    write_worker_result(path, payload, max_bytes=3 * MAX_BYTES)


def observe(key: str) -> dict:
    before = datetime.now(UTC)
    worker = run_json_worker((sys.executable, "-m", "investment_evidence_engine.public_fund_dealing_control",
                              "--child", key), timeout_seconds=30, max_bytes=3 * MAX_BYTES)
    out = {"key": key, "url": url_for(key), "status": "BLOCK",
           "worker_status": worker.status, "elapsed_seconds": worker.elapsed_seconds,
           "raw_body_retained": False}
    if worker.status != "OK" or worker.payload is None:
        return out
    try:
        p = worker.payload
        if (p["key"], p["url"]) != (key, url_for(key)):
            raise ValueError("FUND_DEALING_RECEIPT_SCOPE")
        a, b = (datetime.fromisoformat(p[k]) for k in ("started_at", "finished_at"))
        if a.utcoffset() is None or b.utcoffset() is None or not before <= a <= b <= datetime.now(UTC):
            raise ValueError("FUND_DEALING_RECEIPT_CLOCK")
        out |= {"started_at": p["started_at"], "finished_at": p["finished_at"]}
        if p["status"] != "OBSERVED":
            return out | {"error": p.get("error", "CHILD_BLOCK")}
        captured = datetime.fromisoformat(p["retrieved_at"])
        if captured.utcoffset() is None or not a <= captured <= b:
            raise ValueError("FUND_DEALING_RECEIPT_CLOCK")
        raw = base64.b64decode(p["body"], validate=True)
        validate_pdf_shape(raw, max_bytes=MAX_BYTES)
        if hashlib.sha256(raw).hexdigest() != p["sha256"]:
            raise ValueError("FUND_DEALING_BODY_HASH")
        out |= {"bytes": len(raw), "sha256": p["sha256"], "parent_rehash": "MATCH",
                "retrieved_at": p["retrieved_at"]}
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw), strict=True)
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 5:
            raise ValueError("FUND_DEALING_PAGE_SCOPE")
        pages = tuple(page.extract_text() or "" for page in reader.pages)
        return out | {"status": "OBSERVED", "page_count": len(pages), "fields": parse_notice(key, pages)}
    except Exception as exc:
        msg = str(exc)
        return out | {"error": msg if re.fullmatch(r"[A-Z0-9_]{3,80}", msg) else type(exc).__name__}


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    with ThreadPoolExecutor(max_workers=2) as pool:
        notices = list(pool.map(observe, DOCS))
    complete = all(r["status"] == "OBSERVED" for r in notices)
    result = {"status": "WARN" if complete else "BLOCK", "notices": notices,
              "executor_commit": os.environ["GITHUB_SHA"], "research_only": True,
              "historical_first_availability_verified": False, "actual_order_acceptance_verified": False,
              "complete_notice_chain_verified": False, "decision_authority": False,
              "execution_allowed": False}
    print("PUBLIC_FUND_DEALING " + json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False), flush=True)
    return 0 if complete else 2


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child" and sys.argv[2] in DOCS:
        _child(sys.argv[2], Path(sys.argv[3]))
    elif len(sys.argv) == 1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
