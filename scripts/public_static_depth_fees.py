"""Single bounded public intraday quote/fee integration control, no account."""
from __future__ import annotations

import json
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from investment_evidence_engine.historical_capture import SH, PublicSecurity
from investment_evidence_engine.quote_receipt import (
    capture_quotes,
    cost_walk_latest_quote,
    load_latest_quote,
    persist_quote_receipt,
)

REPO = "riyuewuxing/InvestmentEvidenceEngine"


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    controls = []
    for subject in (PublicSecurity(symbol="000001", asset_type="STOCK"),
                    PublicSecurity(symbol="510300", asset_type="ETF")):
        report = {"subject": subject.model_dump(mode="json"), "status": "BLOCK",
                  "decision_authority": False, "execution_allowed": False}
        try:
            receipt = capture_quotes(subject)
            with TemporaryDirectory() as temp:
                root = Path(temp)
                digest, _ = persist_quote_receipt(root, receipt)
                now = datetime.now(SH)
                loaded = load_latest_quote(root, subject, now=now)
                report["observation"] = loaded
                if loaded["receipt_sha256"] != digest or not loaded["receipt_rehashed"]:
                    raise ValueError("QUOTE_RECEIPT_REHASH_BLOCK")
                # Two separate one-side hypothetical orders, not a stock
                # same-day round trip or a claim about ETF product taxonomy.
                terms = dict(commission_rate=Decimal("0.0003"), minimum_commission=Decimal("5"),
                    transfer_rate=Decimal("0.00001" if subject.asset_type == "STOCK" else "0"),
                    sell_stamp_rate=Decimal("0.0005" if subject.asset_type == "STOCK" else "0"))
                report["sides"] = [cost_walk_latest_quote(root, subject, now=now, side=side,
                    units=100, **terms) for side in ("BUY", "SELL")]
                if all(row["status"] == "CONDITIONAL_STATIC_BOOK_AND_FEE_ONLY" for row in report["sides"]):
                    report["status"] = "WARN"
        except (ValueError, OSError, TypeError, KeyError, ArithmeticError, RuntimeError) as exc:
            report["blocker"] = str(exc) if isinstance(exc, ValueError) and str(exc).isascii() and str(exc).isupper() else type(exc).__name__
        controls.append(report)
    result = {"executor_commit": os.environ["GITHUB_SHA"], "controls": controls,
              "status": "WARN" if all(v["status"] == "WARN" for v in controls) else "BLOCK",
              "raw_provider_bytes_uploaded": False, "actual_broker_fee_verified": False,
              "actual_fills_verified": False, "decision_authority": False, "execution_allowed": False}
    print("PUBLIC_STATIC_DEPTH_AND_FEES " + json.dumps(result, sort_keys=True, allow_nan=False), flush=True)
    return 0 if result["status"] == "WARN" else 2


if __name__ == "__main__":
    raise SystemExit(main())
