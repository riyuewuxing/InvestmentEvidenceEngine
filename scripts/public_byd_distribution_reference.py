"""One fixed A-share ex-day reference check using actual derived issuer receipt."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from decimal import Decimal
from pathlib import Path

from investment_evidence_engine.action_reference import acquire_action_observation
from investment_evidence_engine.byd_action_control import price_reference
from investment_evidence_engine.historical_capture import PublicSecurity, acquire_series
from investment_evidence_engine.snapshot_integrity import strict_json_loads

REPO = "riyuewuxing/InvestmentEvidenceEngine"
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/corporate_actions/observed_002594_2025_distribution.json"
SUBJECT = PublicSecurity(symbol="002594", asset_type="STOCK")
FIRST, LAST = date(2025, 7, 1), date(2025, 8, 1)
RECORD, EX = date(2025, 7, 28), date(2025, 7, 29)


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    report = {"status": "BLOCK", "executor_commit": os.environ["GITHUB_SHA"],
              "subject": SUBJECT.symbol, "pit_safe": False, "decision_authority": False,
              "execution_allowed": False, "raw_provider_bytes_retained": False}
    stage = "ISSUER_DERIVED_RECEIPT"
    try:
        raw = FIXTURE.read_bytes()
        receipt = strict_json_loads(raw)
        r = receipt["receipt"]
        f = r["fields"]
        if (receipt["run_id"] != 45944680758 or receipt["job_id"] != 140326559926
                or receipt["derived_receipt_not_original_pdf"] is not True
                or r["parent_rehash"] != "MATCH" or r["status"] != "OBSERVED"
                or r["source_sha256"] != "1546d4f3cd37864b713d2acbf3f27d0d0592e02627bed2d63cb05a1110126503"
                or (f["record_date"], f["scheduled_ex_and_new_trading_date"]) != (RECORD.isoformat(), EX.isoformat())
                or f["old_share_entitlement_multiplier"] != 3 or f["cash_per_old_share_cny"] != "3.974"):
            raise ValueError("ISSUER_RECEIPT_SCOPE")
        report["issuer_receipt_sha256"] = hashlib.sha256(raw).hexdigest()
        stage = "BAOSTOCK_RAW_PREVIOUS_REFERENCE"
        a = acquire_action_observation(SUBJECT, FIRST, LAST)
        report["action_observation_sha256"] = hashlib.sha256(a.model_dump_json().encode()).hexdigest()
        report["vendor_factor_dates"] = [v.effective_date.isoformat() for v in a.factors]
        stage = "TENCENT_RAW_CLOSE"
        b = acquire_series("tencent", SUBJECT, FIRST, LAST)
        report["other_source_sha256"] = hashlib.sha256(b.model_dump_json().encode()).hexdigest()
        stage = "ALIGNED_REFERENCE_COMPARISON"
        days = tuple(v.session for v in a.raw_rows)
        if (days != tuple(v.session for v in b.closes) or days[0] != FIRST or days[-1] != LAST
                or EX not in days or days.index(EX) == 0 or days[days.index(EX) - 1] != RECORD
                or any(abs(v.close - w.close) > .011 for v, w in zip(a.raw_rows, b.closes))):
            raise ValueError("BYD_RAW_CROSSCHECK_MISMATCH")
        n = days.index(EX)
        prior, current = a.raw_rows[n-1:n+1]
        report.update({"same_observed_sessions": len(days), "raw_close_crosscheck": "MATCH_WITHIN_0.011_CNY",
                       "ex_date_factor_present": EX in {v.effective_date for v in a.factors},
                       "reference": price_reference(Decimal(str(prior.close)), Decimal(str(current.close)),
                                                    Decimal(str(current.previous_reference)))})
        if report["reference"]["vendor_matches_conditional_reference"] and report["ex_date_factor_present"]:
            report["status"] = "WARN"
        else:
            report["blocker"] = "VENDOR_REFERENCE_OR_FACTOR_UNRECONCILED"
    except (ValueError, OSError, KeyError, TypeError, ArithmeticError, RuntimeError) as exc:
        report["failed_stage"] = stage
        report["blocker"] = str(exc) if isinstance(exc, ValueError) and str(exc).isascii() and str(exc).isupper() else type(exc).__name__
    print("PUBLIC_BYD_DISTRIBUTION_REFERENCE " + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    return 0 if report["status"] == "WARN" else 2


if __name__ == "__main__":
    raise SystemExit(main())
