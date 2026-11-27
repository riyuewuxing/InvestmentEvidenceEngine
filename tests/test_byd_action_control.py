import pytest

from investment_evidence_engine.byd_action_control import distribution_examples, parse_pages


def test_tax_base_includes_bonus_but_not_capital_transfer():
    result = distribution_examples()
    assert result["new_shares"] == 300
    assert result["gross_cash_cny"] == "397.400"
    assert result["conditional_tax_cny"] == {"0": "0.00", "0.1": "47.74", "0.2": "95.48"}
    assert not result["actual_payment_verified"]


def test_missing_identity_or_dates_fail_closed():
    with pytest.raises(ValueError, match="BYD_REVIEWED_FIELD_MISMATCH"):
        parse_pages("cancel", ["", "", ""])
    with pytest.raises(ValueError, match="BYD_PAGE_SCOPE"):
        parse_pages("distribution", [""])
