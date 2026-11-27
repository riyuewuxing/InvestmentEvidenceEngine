"""Actual previously observed derived cells; no new data acquisition."""
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from investment_evidence_engine.holding_risk import ShareCashDistribution, share_cash_ex_factor
from investment_evidence_engine.snapshot_integrity import strict_json_loads

BASE = Path(__file__).resolve().parents[1] / "fixtures/corporate_actions"


def test_actual_byd_share_and_cash_terms_reproduce_prior_ex_day_reference():
    terms = strict_json_loads((BASE / "observed_002594_2025_distribution.json").read_bytes())
    price = strict_json_loads((BASE / "observed_002594_2025_distribution_reference.json").read_bytes())
    receipt, observed = terms["receipt"], price["receipt"]
    f, q = receipt["fields"], observed["reference"]
    assert receipt["parent_rehash"] == "MATCH"
    assert price["derived_receipt_not_raw_provider_rows"] is True
    assert observed["same_observed_sessions"] == 24
    assert observed["raw_close_crosscheck"] == "MATCH_WITHIN_0.011_CNY"
    e = ShareCashDistribution(action_id="002594:2025-047", subject_id="002594",
        disclosed_date=date.fromisoformat(f["document_date"]), record_date=date.fromisoformat(f["record_date"]),
        ex_date=date.fromisoformat(f["scheduled_ex_and_new_trading_date"]),
        post_units_numerator=f["old_share_entitlement_multiplier"], pre_units_denominator=1,
        gross_cash_per_old_unit_cny=f["cash_per_old_share_cny"], source_locator=receipt["url"],
        source_sha256=receipt["source_sha256"])
    factor = share_cash_ex_factor(Decimal(q["prior_raw_close_cny"]), Decimal(q["ex_day_raw_close_cny"]), e)
    assert float((factor-1)*100) == pytest.approx(float(q["conditional_gross_wealth_change_pct"]), abs=1e-12)
    assert float((factor-1)*100) == pytest.approx(.3661721068249258)
    assert not q["actual_account_credit_verified"] and not q["official_reference_verified"]
