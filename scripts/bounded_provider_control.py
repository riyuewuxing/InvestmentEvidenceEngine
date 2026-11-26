"""Public-only control of bounded real financial-provider transport.

No private inputs, vendor record export, credentials, admission or execution.
Individual data-source failure is reported, never silently called success.
"""
from __future__ import annotations

import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from zoneinfo import ZoneInfo

from investment_evidence_engine.bounded_worker import run_json_worker, write_worker_result
from investment_evidence_engine.table_wire import pack_frame, unpack_frame

SYMBOL = "600519"
SOURCES = ("indicator", "balance", "profit", "cashflow", "disclosures")
STATEMENTS = {"balance": "资产负债表", "profit": "利润表", "cashflow": "现金流量表"}
SHANGHAI = ZoneInfo("Asia/Shanghai")


def child(kind: str, output: Path) -> int:
    import akshare as ak

    try:
        if kind == "indicator":
            frame = ak.stock_financial_analysis_indicator_em(symbol=SYMBOL + ".SH")
        elif kind in STATEMENTS:
            frame = ak.stock_financial_report_sina(stock="sh" + SYMBOL, symbol=STATEMENTS[kind])
        elif kind == "disclosures":
            end = datetime.now(SHANGHAI).date()
            frame = ak.stock_zh_a_disclosure_report_cninfo(
                symbol=SYMBOL, market="沪深京", keyword="", category="",
                start_date=(end - timedelta(days=90)).strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )
        else:
            return 2
    except Exception as exc:
        write_worker_result(output, {"source": kind, "symbol": SYMBOL, "table": None,
                                    "stage": "FETCH_FAILED", "error_type": type(exc).__name__})
        return 0
    try:
        table = pack_frame(frame)
    except Exception as exc:
        write_worker_result(output, {"source": kind, "symbol": SYMBOL, "table": None,
                                    "stage": "ENCODE_FAILED", "error_type": type(exc).__name__})
        return 0
    write_worker_result(output, {"source": kind, "symbol": SYMBOL, "table": table,
                                "stage": "TABLE_RETURNED", "error_type": None})
    return 0


def observe(kind: str) -> dict:
    result = run_json_worker((sys.executable, str(Path(__file__).resolve()), "--child", kind),
                             timeout_seconds=35)
    row = {"source": kind, "worker_status": result.status, "elapsed_seconds": result.elapsed_seconds,
           "source_status": "NOT_OBSERVED", "rows": 0}
    if result.status != "OK":
        return row
    payload = result.payload
    if not isinstance(payload, dict) or set(payload) != {"source", "symbol", "table", "stage", "error_type"}:
        return row | {"source_status": "INVALID_ENVELOPE"}
    if payload["source"] != kind or payload["symbol"] != SYMBOL:
        return row | {"source_status": "IDENTITY_MISMATCH"}
    if payload["stage"] in {"FETCH_FAILED", "ENCODE_FAILED"}:
        return row | {"source_status": payload["stage"], "error_type": payload["error_type"]}
    if payload["stage"] != "TABLE_RETURNED" or payload["error_type"] is not None:
        return row | {"source_status": "INVALID_STAGE"}
    try:
        frame = unpack_frame(payload["table"])
        if frame is None or frame.empty:
            return row | {"source_status": "EMPTY"}
        required = {"REPORT_DATE"} if kind == "indicator" else (
            {"公告标题", "公告时间", "公告链接", "代码"} if kind == "disclosures" else {"报告日"})
        if not required.issubset(frame.columns):
            return row | {"source_status": "MISSING_REQUIRED_COLUMNS"}
        if kind == "indicator" and "SECURITY_CODE" in frame.columns:
            if any(str(v) != SYMBOL for v in frame["SECURITY_CODE"]):
                return row | {"source_status": "VENDOR_SYMBOL_MISMATCH"}
        if kind == "disclosures" and any(str(v) != SYMBOL for v in frame["代码"]):
            return row | {"source_status": "VENDOR_SYMBOL_MISMATCH"}
        reconstructed = pack_frame(frame)
        if reconstructed != payload["table"]:
            return row | {"source_status": "ROUNDTRIP_MISMATCH"}
        raw = json.dumps(reconstructed, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode("utf-8")
    except (ValueError, TypeError):
        return row | {"source_status": "INVALID_TABLE"}
    return row | {"source_status": "OBSERVED_TRANSPORT_ONLY", "rows": len(frame),
                  "columns": len(frame.columns), "normalized_sha256": hashlib.sha256(raw).hexdigest(),
                  "roundtrip_equal": True}


def main() -> int:
    if len(sys.argv) == 4 and sys.argv[1] == "--child":
        return child(sys.argv[2], Path(sys.argv[3]))
    if len(sys.argv) != 1:
        return 2
    with ThreadPoolExecutor(max_workers=4) as pool:
        reports = list(pool.map(observe, SOURCES))
    observed = sum(r["source_status"] == "OBSERVED_TRANSPORT_ONLY" for r in reports)
    summary = {"symbol": SYMBOL, "observed_at": datetime.now(SHANGHAI).isoformat(),
               "akshare_version": version("akshare"), "attempted": len(SOURCES), "observed": observed,
               "reports": reports, "raw_vendor_body_archived": False,
               "pit_verified": False, "decision_authority": False}
    print("PUBLIC_BOUNDED_PROVIDER_CONTROL " + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if observed == len(SOURCES) else 2


if __name__ == "__main__":
    raise SystemExit(main())
