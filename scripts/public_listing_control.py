"""Bounded actual BaoStock/Sina code-set control, no raw rows in logs or repo."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from investment_evidence_engine.bounded_worker import run_json_worker, write_worker_result
from investment_evidence_engine.listing_comparison import compare_code_sets, normalize_codes

SHANGHAI = ZoneInfo("Asia/Shanghai")


def child(provider: str, day: str, path: Path) -> int:
    try:
        if provider == "baostock":
            import baostock as bs

            login = bs.login()
            if login.error_code != "0":
                raise RuntimeError("login rejected")
            try:
                response = bs.query_all_stock(day=day)
                if response.error_code != "0" or "code" not in response.fields:
                    raise RuntimeError("listing query rejected")
                idx = response.fields.index("code")
                codes = []
                while response.next():
                    codes.append(response.get_row_data()[idx])
                    if len(codes) > 12_000:
                        raise ValueError("oversized security list")
                if response.error_code != "0":
                    raise RuntimeError("listing query incomplete")
                fn = bs.query_all_stock
            finally:
                bs.logout()
        elif provider == "sina":
            import akshare as ak

            fn = ak.stock_zh_a_spot_sina
            frame = fn()
            fields = [name for name in ("代码", "code", "symbol") if name in frame.columns]
            if len(fields) != 1 or not frame.columns.is_unique:
                raise ValueError("ambiguous security code column")
            codes = frame[fields[0]].tolist()
        else:
            return 2
        write_worker_result(path, {
            "provider": provider, "requested_day": day,
            "observed_at": datetime.now(UTC).isoformat(), "codes": codes,
            "callable_module": fn.__module__,
            "callable_source_sha256": hashlib.sha256(inspect.getsource(fn).encode()).hexdigest(),
            "error": None,
        })
    except Exception as exc:
        write_worker_result(path, {"provider": provider, "requested_day": day,
                                   "error": type(exc).__name__})
    return 0


def observe(provider: str, day: str, seconds: int) -> tuple[dict, list | None]:
    result = run_json_worker(
        (sys.executable, __file__, "--child", provider, day), timeout_seconds=seconds,
    )
    record = {"provider": provider, "status": result.status, "elapsed_seconds": result.elapsed_seconds}
    payload = result.payload
    if result.status != "OK" or not isinstance(payload, dict):
        return record, None
    if payload.get("provider") != provider or payload.get("requested_day") != day or payload.get("error"):
        record.update(status="PROVIDER_BLOCK", error=payload.get("error"))
        return record, None
    try:
        _, stats = normalize_codes(payload.get("codes"), require_exchange=provider == "baostock")
    except ValueError:
        record.update(status="INVALID_SECURITY_LIST")
        return record, None
    record.update({k: payload[k] for k in ("observed_at", "callable_module", "callable_source_sha256")})
    record["code_stats"] = stats
    if (stats["invalid_count"] or stats["duplicate_count"]
            or min(stats["sh_count"], stats["sz_count"]) < 1000):
        record["status"] = "INSUFFICIENT_OR_AMBIGUOUS_CODES"
        return record, None
    return record, payload["codes"]


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("public repository required")
    local = datetime.now(SHANGHAI)
    if local.weekday() >= 5 or local.hour < 18:
        raise SystemExit("after-close weekday control only")
    day = local.date().isoformat()
    receipt = {"requested_trade_day": day, "executor_commit": os.environ["GITHUB_SHA"],
               "capture_started_at": local.isoformat(), "source_independence_verified": False,
               "raw_provider_bytes_retained": False, "decision_authority": False,
               "execution_allowed": False, "providers": []}
    reference, left = observe("baostock", day, 45)
    receipt["providers"].append(reference)
    if left is not None:
        snapshot, right = observe("sina", day, 85)
        receipt["providers"].append(snapshot)
        if right is not None:
            receipt["comparison"] = compare_code_sets(left, right)
    receipt["status"] = "WARN" if "comparison" in receipt and receipt["comparison"]["status"] != (
        "BLOCK_INCOMPLETE_OR_AMBIGUOUS") else "BLOCK"
    receipt["finished_at"] = datetime.now(UTC).isoformat()
    raw = json.dumps(receipt, ensure_ascii=False, sort_keys=True, allow_nan=False)
    print("PUBLIC_LISTING_RECEIPT_SHA256 " + hashlib.sha256(raw.encode()).hexdigest(), flush=True)
    print("PUBLIC_LISTING_RECEIPT " + raw, flush=True)
    return 0 if receipt["status"] == "WARN" else 2


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--child":
        raise SystemExit(child(sys.argv[2], sys.argv[3], Path(sys.argv[4])))
    raise SystemExit(main())
