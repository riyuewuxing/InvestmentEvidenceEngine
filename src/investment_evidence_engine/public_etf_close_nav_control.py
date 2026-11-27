"""One fixed retrospective ETF close/NAV crosscheck. No live trading signal."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from decimal import Decimal
from pathlib import Path

from .etf_report_diagnostics import closing_premium, compare_reports
from .historical_capture import PublicSecurity, observe_pair

RECEIPT = Path("controls/etf-q3-2026-observed-fields.json")
RECEIPT_SHA256 = "13a1c3a69dce4470ea267ce7024b47162f2dac78743a19e9eedb6ee4aac0da19"
FIRST = date(2026, 8, 31)
LAST = date(2026, 9, 30)
SYMBOLS = ("510330", "510320")
DOCUMENT_HASHES = (
    "f0b3d948633558c55317fbc852257eb9657dfef3c47e89d5a9e5fe80ab099826",
    "bce1bb11a2e0898b37f174ebbb96bba30794167a0cffc4e8b3182365dd86241c",
)


def verify_report_fields(raw: bytes) -> dict:
    if hashlib.sha256(raw).hexdigest() != RECEIPT_SHA256:
        raise ValueError("ETF_REPORT_RECEIPT_HASH")
    data = json.loads(raw)
    docs = data["documents"]
    if (data["source_run"] != 45958440503 or data["source_job"] != 140370277263
            or data["source_executor_commit"] != "cd13bc608947a1fb72f4badf34a0c9c1c72564a6"
            or tuple(d["symbol"] for d in docs) != SYMBOLS
            or tuple(d["sha256"] for d in docs) != DOCUMENT_HASHES
            or any(d["fields"]["symbol"] != d["symbol"] for d in docs)):
        raise ValueError("ETF_REPORT_RECEIPT_SCOPE")
    compare_reports(docs[0]["fields"], docs[1]["fields"])
    return data


def run_control() -> dict:
    raw = RECEIPT.read_bytes()
    data = verify_report_fields(raw)
    docs = data["documents"]
    subjects = tuple(PublicSecurity(symbol=s, asset_type="ETF") for s in SYMBOLS)
    pair, series = observe_pair(*subjects, FIRST, LAST, providers=("sina", "tencent"))
    outputs = []
    for d in docs:
        group = [s for s in series if s.subject_id == d["symbol"]]
        prices = {s.source_label: str(Decimal(str(s.closes[-1].close))) for s in group}
        dates = {s.source_label: s.closes[-1].session.isoformat() for s in group}
        exact = (set(prices) == {"sina", "tencent"} and len(set(prices.values())) == 1
                 and set(dates.values()) == {LAST.isoformat()})
        row = {"symbol": d["symbol"], "close_by_source": prices, "session_by_source": dates,
               "exact_terminal_match": exact, "document_sha256": d["sha256"],
               "normalized_row_counts": {s.source_label: len(s.closes) for s in group}}
        if exact:
            row["retrospective_close_nav"] = closing_premium(
                d["fields"], symbol=d["symbol"], session=LAST.isoformat(), raw_close=next(iter(prices.values())))
        outputs.append(row)
    return {"status": "WARN" if all(x["exact_terminal_match"] for x in outputs) else "BLOCK",
            "report_fields_file_sha256": hashlib.sha256(raw).hexdigest(), "source_run": data["source_run"],
            "observations": outputs, "source_pair_crosscheck": pair, "first": FIRST.isoformat(),
            "last": LAST.isoformat(), "source_independence_verified": False,
            "raw_provider_body_retained": False, "historical_vintage_verified": False,
            "execution_allowed": False, "decision_authority": False}


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("public repository required")
    report = run_control() | {"executor_commit": os.environ["GITHUB_SHA"]}
    print("PUBLIC_ETF_CLOSE_NAV_CONTROL " + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    return 0 if report["status"] == "WARN" else 2


if __name__ == "__main__":
    raise SystemExit(main())
