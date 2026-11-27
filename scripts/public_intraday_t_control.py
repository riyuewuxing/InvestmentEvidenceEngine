"""Single fixed public retrospective control; no raw rows emitted."""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from importlib.metadata import version

from investment_evidence_engine.contracts import canonical_sha256
from investment_evidence_engine.intraday_close_reference import normalized_closes, retrospective_t_close_sensitivity

DAY = date(2026, 11, 27)
REPO = "riyuewuxing/InvestmentEvidenceEngine"


def fetch_baostock():
    import baostock as bs

    if bs.login().error_code != "0":
        raise ValueError("BAOSTOCK_LOGIN_FAILED")
    try:
        def query(result):
            if result.error_code != "0":
                raise ValueError("BAOSTOCK_QUERY_FAILED")
            rows = []
            while result.next():
                row = result.get_row_data()
                if len(row) != len(result.fields) or len(rows) >= 200:
                    raise ValueError("BAOSTOCK_ROW_BOUND")
                rows.append(dict(zip(result.fields, row)))
            if result.error_code != "0":
                raise ValueError("BAOSTOCK_QUERY_FAILED")
            return rows
        scope = dict(start_date=DAY.isoformat(), end_date=DAY.isoformat())
        cal = query(bs.query_trade_dates(**scope))
        daily = query(bs.query_history_k_data_plus("sz.000001", "date,code,open,high,low,close,preclose,adjustflag,tradestatus,isST",
                                                    frequency="d", adjustflag="3", **scope))
        if len(daily) != 1 or len(cal) != 1 or cal[0].get("calendar_date") != DAY.isoformat():
            raise ValueError("BAOSTOCK_DAILY_CALENDAR_UNAVAILABLE")
        daily[0]["calendar_open"] = cal[0].get("is_trading_day") == "1"
        rows = query(bs.query_history_k_data_plus("sz.000001", "date,time,code,open,high,low,close,volume,adjustflag",
                                                   frequency="5", adjustflag="3", **scope))
        for row in rows:
            raw = row["time"]
            if len(raw) != 17 or not raw.isascii() or not raw.isdigit() or raw[-3:] != "000" or row["date"] != DAY.isoformat():
                raise ValueError("BAOSTOCK_MINUTE_TIME_SCHEMA")
            row["time"] = datetime.strptime(raw[:14], "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
        return {"rows": rows, "daily": daily[0]}
    finally:
        bs.logout()


def fetch_sina():
    import akshare as ak

    frame = ak.stock_zh_a_minute(symbol="sz000001", period="5", adjust="")
    if frame is None or frame.empty or not {"day","open","high","low","close","volume"}.issubset(frame.columns):
        raise ValueError("SINA_MINUTE_SCHEMA_UNAVAILABLE")
    # The endpoint may return a long tail; only explicit requested session
    # rows enter the bounded parent transport. No fabricated identity fields.
    rows = []
    for row in frame[["day","open","high","low","close","volume"]].to_dict("records"):
        stamp = str(row["day"]).replace("T", " ")
        if stamp[:10] == DAY.isoformat():
            rows.append({k: str(v) for k, v in row.items() if k != "day"} | {"time": stamp})
    if not rows or len(rows) > 200:
        raise ValueError("SINA_TARGET_SESSION_UNAVAILABLE")
    return {"rows": rows}


def child(source):
    try:
        # Provider diagnostics never enter public logs.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            data = fetch_baostock() if source == "baostock" else fetch_sina()
        print(json.dumps({"status": "OBSERVED", "data": data, "decoded_sha256": canonical_sha256(data),
                          "retrieved_at": datetime.now(UTC).isoformat(),
                          "package_version": version("baostock" if source == "baostock" else "akshare")}, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "UNAVAILABLE", "error": type(exc).__name__,
                          "code": str(exc) if str(exc).startswith(("BAOSTOCK_", "SINA_")) and len(str(exc)) < 100 else "PROVIDER_FAILURE"}))
        return 0


def observe(source):
    try:
        out = subprocess.run([sys.executable, __file__, "--worker", source],
                             capture_output=True, timeout=65, check=False)
        if out.returncode or len(out.stdout) > 256 * 1024:
            return {"status": "UNAVAILABLE", "error": "CHILD_EXIT_OR_BOUND"}
        data = json.loads(out.stdout)
        if data.get("status") == "OBSERVED" and data["decoded_sha256"] != canonical_sha256(data["data"]):
            return {"status": "UNAVAILABLE", "error": "CHILD_HASH_MISMATCH"}
        return data
    except subprocess.TimeoutExpired:
        return {"status": "UNAVAILABLE", "error": "WATCHDOG_TIMEOUT_65S"}
    except (ValueError, TypeError, KeyError, OSError):
        return {"status": "UNAVAILABLE", "error": "CHILD_TRANSPORT_INVALID"}


def main():
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = dict(zip(("baostock","sina"), pool.map(observe, ("baostock","sina"))))
    clean = {}
    diagnostics = {}
    for source, result in results.items():
        diagnostics[source] = {k: v for k, v in result.items() if k != "data"}
        if result.get("status") != "OBSERVED":
            continue
        try:
            reference = normalized_closes(result["data"]["rows"], session=DAY, source=source, symbol="000001")
            clean[source] = reference
            diagnostics[source] |= {k: v for k, v in reference.items() if k != "bars"}
        except (ValueError, KeyError, TypeError):
            diagnostics[source]["status"] = "NORMALIZATION_BLOCK"
    now = datetime.now(UTC)
    if "baostock" in clean:
        comparison = retrospective_t_close_sensitivity(clean["baostock"], clean.get("sina"),
                        results["baostock"]["data"]["daily"], session=DAY, evaluated_at=now)
    else:
        comparison = {"status": "BLOCK", "reason": "PRIMARY_UNAVAILABLE", "decision_authority": False}
    report = {"executor_commit": os.environ["GITHUB_SHA"], "subject_id": "000001",
              "session_date": DAY.isoformat(), "observed_at": now.isoformat(),
              "sources": diagnostics, "comparison": comparison,
              "raw_rows_retained": False, "raw_provider_wire_bytes_verified": False,
              "formal_admission": False, "decision_authority": False, "execution_allowed": False}
    print("PUBLIC_INTRADAY_T_CLOSE_CONTROL " + json.dumps(report, sort_keys=True), flush=True)
    return 0 if comparison["status"] == "RETROSPECTIVE_CLOSE_SENSITIVITY_ONLY" else 2


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--worker" and sys.argv[2] in {"baostock","sina"}:
        raise SystemExit(child(sys.argv[2]))
    raise SystemExit(main())
