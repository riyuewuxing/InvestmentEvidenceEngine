from decimal import Decimal

import pytest

from investment_evidence_engine.dividend_tax_control import parse_policy
from investment_evidence_engine.dividend_tax_sensitivity import uniform_tax_tiers


def test_tax_scenarios_only_affect_gross_entitlement():
    result = uniform_tax_tiers(-11.6, 0.72)
    rows = result["scenarios"]
    assert [Decimal(row["price_plus_nominal_net_entitlement_change_pct"]) for row in rows] == [
        Decimal("-10.88"), Decimal("-10.952"), Decimal("-11.024")]
    assert not result["actual_tax_rate_assigned"]
    assert not result["actual_payment_verified"]
    assert not result["decision_authority"]
    flat = uniform_tax_tiers(0, 0)
    assert all(Decimal(row["nominal_tax_increment_pp"]) == 0 for row in flat["scenarios"])


@pytest.mark.parametrize("base,gross", [(True, 1), (0, -1), (float("nan"), 1),
                                      (-100, 1), (0, float("inf"))])
def test_invalid_inputs_block(base, gross):
    with pytest.raises(ValueError):
        uniform_tax_tiers(base, gross)


def test_policy_fields_missing_block():
    with pytest.raises(ValueError, match="DIVIDEND_TAX_POLICY_FIELDS"):
        parse_policy("rule_2015", b"<html>wrong document</html>")
