"""Actual selected-stock action dates and cash-reference arithmetic.

The 2025 source receipt is the observed prior control's derived log (not
retained original bytes). Re-observe 2026 source for newly checked page/terms,
compare its prior source digest, then acquire actual BaoStock status/factors,
calendar, and independent raw-close route. No claim of historical vintage.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from investment_evidence_engine.action_reference import (
    acquire_action_observation,
    audit_cash_actions,
)
from investment_evidence_engine.cash_entitlement import CashEntitlementTerms
from investment_evidence_engine.historical_capture import SH, PublicSecurity, acquire_series
from investment_evidence_engine.holding_risk import CashDistribution, CashDistributionInputs
from investment_evidence_engine.issuer_entitlement_control import observe
from investment_evidence_engine.market_calendar import acquire_calendar
from investment_evidence_engine.snapshot_integrity import strict_json_loads

REPO = "riyuewuxing/InvestmentEvidenceEngine"
SUBJECT = PublicSecurity(symbol="000035", asset_type="STOCK")
FIRST, LAST = date(2025, 1, 2), date(2026, 11, 25)
PRIOR_2025_SHA = "18ad09cf3d97f04fdff90b2ee0bee63380a021862098caefbbd9455cc97b15e8"
PRIOR_2026_SHA = "206b923f9f1e0d12b6e5b20d77dc3b39eb57058da141b5358c2dd49952d540af"
PRIOR_RECEIPT = Path(__file__).resolve().parents[1]/"fixtures/corporate_actions/observed_000035_2025_cash_receipt.json"


def terms_from_receipt(receipt: dict) -> CashEntitlementTerms:
    if receipt["status"] != "OBSERVED" or receipt["parent_rehash"] != "MATCH" or receipt["temporary_rehash"] != "MATCH":
        raise ValueError("SELECTED_ACTION_SOURCE_NOT_OBSERVED")
    x = receipt["fields"]
    terms = CashEntitlementTerms(symbol=x["symbol"], disclosed_date=date.fromisoformat(x["disclosed_date"]),
        record_date=date.fromisoformat(x["record_date"]), ex_date=date.fromisoformat(x["ex_date"]),
        source_locator=x["source_locator"], total_shares=x["total_shares"], excluded_shares=x["excluded_shares"],
        gross_per_share=Decimal(x["gross_entitlement_per_share_cny"]),
        declared_total_cash=Decimal(x["declared_total_cash_cny"]),
        declared_reference_deduction=Decimal(x["reference_deduction_per_share_cny"]))
    computed = terms.checked()
    if any(x.get(k) != v for k, v in computed.items()):
        raise ValueError("SELECTED_ACTION_RECEIPT_TERMS_MISMATCH")
    return terms


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    report = {"status": "BLOCK", "executor_commit": os.environ["GITHUB_SHA"],
              "subject": SUBJECT.symbol, "first": FIRST.isoformat(), "last": LAST.isoformat(),
              "historical_vintage_verified": False, "corporate_action_coverage_verified": False,
              "actual_execution_verified": False, "decision_authority": False,
              "execution_allowed": False, "raw_provider_bytes_retained": False}
    with TemporaryDirectory() as temp:
        receipt_file = PRIOR_RECEIPT.read_bytes()
        prior = strict_json_loads(receipt_file)
        report["prior_2025_receipt_file_sha256"] = hashlib.sha256(receipt_file).hexdigest()
        if (prior["run_id"] != 45856529066 or prior["job_id"] != 140036250613
                or prior["derived_receipt_not_original_pdf"] is not True
                or prior["receipt"]["source_sha256"] != PRIOR_2025_SHA):
            raise ValueError("SELECTED_ACTION_PRIOR_RECEIPT_IDENTITY")
        report["prior_2025_derived_receipt"] = prior
        fresh = observe("cash_2026", Path(temp))
        report["new_2026_observation"] = fresh
        report["prior_2026_original_sha256"] = PRIOR_2026_SHA
        if fresh.get("source_sha256") != PRIOR_2026_SHA:
            report["blocker"] = "SELECTED_ACTION_2026_ORIGINAL_VERSION_UNCONFIRMED"
        else:
            report["prior_2026_source_version_match"] = True
            try:
                terms = (terms_from_receipt(prior["receipt"]), terms_from_receipt(fresh))
                if tuple(t.ex_date for t in terms) != (date(2025, 8, 6), date(2026, 8, 20)):
                    raise ValueError("SELECTED_ACTION_EVENT_SCOPE")
                events = CashDistributionInputs(events=tuple(CashDistribution(
                    subject_id=t.symbol, disclosed_date=t.disclosed_date, ex_date=t.ex_date,
                    gross_cash_per_unit_cny=float(t.gross_per_share), source_locator=t.source_locator)
                    for t in terms))
                stage = "BAOSTOCK_ACTION_STATUS"
                obs = acquire_action_observation(SUBJECT, FIRST, LAST)
                path = Path(temp)/"action_observation.json"
                body = obs.model_dump_json().encode()
                path.write_bytes(body)
                readback = path.read_bytes()
                if readback != body:
                    raise ValueError("SELECTED_ACTION_OBSERVATION_REOPEN")
                obs = type(obs).model_validate_json(readback)
                report["action_observation"] = {"sha256": hashlib.sha256(body).hexdigest(),
                    "rows": len(obs.raw_rows), "factor_dates": [r.effective_date.isoformat() for r in obs.factors],
                    "normalized_rehash": "MATCH",
                    "vendor_raw_adjustflag_and_daily_tradestatus_checked": True,
                    "actual_fill_or_st_history_verified": False, "observed_at": obs.observed_at.isoformat()}
                stage = "BAOSTOCK_CALENDAR"
                calendar = acquire_calendar(FIRST, LAST)
                report["calendar"] = {"rows": len(calendar.rows), "sha256": hashlib.sha256(
                    calendar.model_dump_json().encode()).hexdigest(),
                    "observed_at": calendar.observed_at.isoformat()}
                stage = "TENCENT_RAW_CLOSE"
                other = acquire_series("tencent", SUBJECT, FIRST, LAST)
                report["other_close"] = {"rows": len(other.closes), "sha256": hashlib.sha256(
                    other.model_dump_json().encode()).hexdigest()}
                stage = "ACTION_REFERENCE_COMPARISON"
                now = datetime.now(SH)
                report["legacy_assumption_audit"] = audit_cash_actions(obs, other, calendar, events, now=now)
                report["explicit_terms_audit"] = audit_cash_actions(
                    obs, other, calendar, events, now=now, reference_terms=terms)
                if report["explicit_terms_audit"]["status"] == "OBSERVED_ACTION_INTERVAL_RECONCILED":
                    report["status"] = "WARN"
                else:
                    report["blocker"] = "SELECTED_ACTION_INTERVAL_UNRECONCILED"
            except (ValueError, TypeError, OSError, KeyError, ArithmeticError, RuntimeError) as exc:
                code = str(exc)
                report["blocker"] = code if code.isascii() and code.isupper() and code.replace("_","").isalnum() else type(exc).__name__
                report["failed_stage"] = locals().get("stage", "EXPLICIT_TERMS")
    print("PUBLIC_SELECTED_ACTION_RECONCILIATION " + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    return 0 if report["status"] == "WARN" else 2


if __name__ == "__main__":
    raise SystemExit(main())
