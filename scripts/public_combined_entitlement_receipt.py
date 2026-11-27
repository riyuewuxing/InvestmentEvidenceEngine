"""Fixed public BYD-vs-ETF combined entitlement receipt, not total return or PIT."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from investment_evidence_engine.historical_capture import PublicSecurity, observe_pair
from investment_evidence_engine.historical_receipt import (
    HistoricalCaptureFailure,
    HistoricalReceipt,
    load_receipt,
    persist_receipt,
)
from investment_evidence_engine.holding_risk import (
    ShareCashDistribution,
    ShareCashDistributionInputs,
    share_cash_ex_factor,
)
from investment_evidence_engine.market_calendar import acquire_calendar
from investment_evidence_engine.snapshot_integrity import strict_json_loads

REPO = "riyuewuxing/InvestmentEvidenceEngine"
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/corporate_actions/observed_002594_2025_distribution.json"
FIRST, LAST = date(2025, 6, 16), date(2025, 9, 30)
SH = ZoneInfo("Asia/Shanghai")


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    report = {"status": "BLOCK", "executor_commit": os.environ["GITHUB_SHA"],
              "first": FIRST.isoformat(), "last": LAST.isoformat(),
              "decision_authority": False, "execution_allowed": False, "pit_safe": False,
              "raw_provider_bytes_retained": False}
    stage = "ISSUER_RECEIPT"
    try:
        raw = FIXTURE.read_bytes()
        derived = strict_json_loads(raw)
        source = derived["receipt"]
        f = source["fields"]
        if (derived["run_id"] != 45944680758 or derived["job_id"] != 140326559926
                or derived["derived_receipt_not_original_pdf"] is not True
                or source["parent_rehash"] != "MATCH" or source["status"] != "OBSERVED"
                or source["source_sha256"] != "1546d4f3cd37864b713d2acbf3f27d0d0592e02627bed2d63cb05a1110126503"
                or (f["record_date"], f["scheduled_ex_and_new_trading_date"]) != ("2025-07-28", "2025-07-29")
                or f["old_share_entitlement_multiplier"] != 3 or f["cash_per_old_share_cny"] != "3.974"):
            raise ValueError("ISSUER_RECEIPT_SCOPE")
        event = ShareCashDistribution(action_id="BYD_2025_A_SHARE_DISTRIBUTION", subject_id="002594",
            disclosed_date=date.fromisoformat(f["path_date"]), record_date=date.fromisoformat(f["record_date"]),
            ex_date=date.fromisoformat(f["scheduled_ex_and_new_trading_date"]),
            post_units_numerator=f["old_share_entitlement_multiplier"], pre_units_denominator=1,
            gross_cash_per_old_unit_cny=f["cash_per_old_share_cny"], source_locator=source["url"],
            source_sha256=source["source_sha256"])
        report["issuer_derived_fixture_sha256"] = hashlib.sha256(raw).hexdigest()
        report["issuer_original_bytes_reacquired"] = False
        candidate = PublicSecurity(symbol="002594", asset_type="STOCK")
        alternative = PublicSecurity(symbol="510300", asset_type="ETF")
        stage = "PAIR_OBSERVATION"
        summary, sources = observe_pair(candidate, alternative, FIRST, LAST,
                                        providers=("sina", "baostock", "tencent"))
        report["pair"] = {k: summary.get(k) for k in ("status", "crosscheck", "candidate_providers",
                          "alternative_providers", "attempted_providers", "failures")}
        if summary["status"] != "OBSERVED_REFERENCE_ONLY" or summary["crosscheck"] != "MATCH":
            raise ValueError("COMBINED_PAIR_BLOCK")
        stage = "CALENDAR"
        cal = acquire_calendar(FIRST, LAST)
        stage = "V3_PERSIST_REOPEN_RECOMPUTE"
        receipt = HistoricalReceipt(schema_version="3", candidate=candidate, alternative=alternative,
            first_requested=FIRST, last_completed=LAST, observed_at=datetime.now(SH),
            akshare_version=version("akshare"), attempted_providers=tuple(summary["attempted_providers"]),
            failures=tuple(HistoricalCaptureFailure.model_validate(f) for f in summary["failures"]),
            series=sources, calendar=cal, share_cash_distributions=ShareCashDistributionInputs(events=(event,)))
        with TemporaryDirectory() as temp:
            folder = Path(temp)
            digest, computed = persist_receipt(folder, receipt)
            loaded = load_receipt(folder, candidate, alternative, LAST, now=datetime.now(SH))
            risk = loaded["holding_reference"]
            if (loaded["normalized_observation_sha256"] != digest
                    or not loaded["normalized_observation_rehashed"]
                    or risk != computed["holding_reference"]
                    or risk["status"] != "HISTORICAL_HOLDING_REFERENCE_ONLY"
                    or risk.get("share_cash_scenario_status") != "CONDITIONAL_GROSS_EX_CLOSE_REINVESTMENT_ONLY"
                    or len(risk["share_cash_event_audit"]["included"]) != 1):
                raise ValueError("COMBINED_RECEIPT_BLOCK")
            selected = next(s for s in sources if s.subject_id == candidate.symbol)
            closes = {v.session: Decimal(str(v.close)) for v in selected.closes}
            prior, current = closes[event.record_date], closes[event.ex_date]
            if (prior, current) != (Decimal("337"), Decimal("111.42")):
                raise ValueError("PRIOR_OBSERVED_EX_CELLS_CHANGED")
            factor = share_cash_ex_factor(prior, current, event)
            if risk["share_cash_total_return_certified"] or risk["decision_authority"]:
                raise ValueError("AUTHORITY_BOUNDARY")
            report.update({"status": "WARN", "normalized_receipt_sha256": digest,
                "normalized_receipt_rehash": "MATCH", "schema_version": receipt.schema_version,
                "session_count": risk["session_count"], "issuer_event": event.model_dump(mode="json"),
                "ex_factor_return_pct": str((factor - 1) * 100),
                "raw_full_window_pct": risk["raw_full_window_pct"],
                "share_cash_full_window_pct": risk["share_cash_full_window_pct"],
                "share_cash_scenario_basis": risk["share_cash_scenario_basis"],
                "share_cash_event_audit": risk["share_cash_event_audit"],
                "share_cash_scenario_windows": risk["share_cash_scenario_windows"],
                "corporate_action_coverage_verified": False, "actual_account_credit_verified": False,
                "actual_tax_and_cost_verified": False, "historical_vintage_verified": False,
                "alternative_other_distributions_not_accounted_for": True,
                "share_cash_total_return_certified": False, "temporary_receipt_only": True})
    except (ValueError, OSError, KeyError, TypeError, RuntimeError, ArithmeticError) as exc:
        report["failed_stage"] = stage
        report["blocker"] = str(exc) if isinstance(exc, ValueError) and str(exc).isascii() and str(exc).isupper() else type(exc).__name__
    print("PUBLIC_COMBINED_ENTITLEMENT_RECEIPT " + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    return 0 if report["status"] == "WARN" else 2


if __name__ == "__main__":
    raise SystemExit(main())
