from datetime import date

import pytest

from investment_evidence_engine.valuation_sensitivity import (
    EarningsCase,
    ProportionalCostAssumptions,
    ValuationSensitivityInputs,
    valuation_sensitivity,
)


def inputs(**changes):
    data=dict(subject_id="synthetic",market_session=date(2026,11,25),horizon_calendar_days=365,
        capitalization_cny=1000.,capitalization_basis_note="synthetic cap",
        reference_ttm_parent_profit_cny=10.,reference_profit_basis_note="synthetic trailing",
        terminal_profit_cases=(EarningsCase(label="one",annual_parent_profit_cny=25.,basis_note="assumption"),
                               EarningsCase(label="loss",annual_parent_profit_cny=-1.,basis_note="assumption")),
        terminal_pe_multiples=(20.,40.),target_return_pcts=(0.,10.))
    data.update(changes)
    return ValuationSensitivityInputs(**data)


def test_grid_and_reverse_hurdles_are_exact_and_no_net_assumptions():
    result=valuation_sensitivity(inputs())
    assert result["current_implied_pe_on_reference_profit"]==100.
    assert len(result["scenarios"])==4
    assert result["scenarios"][0]["conditional_price_return_pct"]==pytest.approx(-50)
    assert result["scenarios"][1]["conditional_price_return_pct"]==pytest.approx(0)
    assert result["scenarios"][2]["status"]=="PE_NOT_APPLICABLE_TO_NONPOSITIVE_EARNINGS"
    assert "conditional_price_return_pct" not in result["scenarios"][2]
    assert result["scenarios"][0]["conditional_net_return_pct"] is None
    assert result["reverse_hurdles"][0]["required_profit_for_price_return_cny"]==50.
    assert result["reverse_hurdles"][1]["required_profit_for_price_return_cny"]==pytest.approx(55.)
    assert result["reverse_hurdles"][0]["required_profit_to_reference_ttm_x"]==5.
    assert not result["expected_return_estimated"] and not result["decision_authority"]
    assert not result["scenario_probabilities_estimated"] and not result["fair_value_estimated"]


def test_explicit_costs_and_cash_assumptions_and_reverse_net_math():
    costs=ProportionalCostAssumptions(entry_cost_bps=100.,exit_cost_bps=200.,
        dividend_tax_pct=10.,note="explicit synthetic assumptions")
    result=valuation_sensitivity(inputs(future_cash_distribution_yield_pct=5.,
        future_cash_distribution_basis_note="hypothetical payout",costs=costs))
    row=result["scenarios"][1]
    assert row["conditional_gross_total_return_pct"]==pytest.approx(5.)
    assert row["conditional_net_return_pct"]==pytest.approx((1025/1010-1)*100)
    required=result["reverse_hurdles"][2]["required_profit_for_conditional_net_return_cny"]
    assert required==pytest.approx((1010-45)/.98/40)
    assert (required*40*.98+45)/1010==pytest.approx(1.)


@pytest.mark.parametrize("changes",[
    {"terminal_pe_multiples":(20.,20.)},{"terminal_pe_multiples":(-20.,)},
    {"terminal_pe_multiples":(float("inf"),)},{"target_return_pcts":(-100.,)},
    {"reference_profit_basis_note":None},{"reference_profit_basis_note":" "},
    {"future_cash_distribution_yield_pct":0.},{"future_cash_distribution_basis_note":"assumption"},
    {"capitalization_cny":float("nan")},{"horizon_calendar_days":0},
])
def test_invalid_assumptions_rejected(changes):
    with pytest.raises(ValueError):
        inputs(**changes)


def test_costs_without_explicit_payout_rejected_and_model_copy_revalidated():
    costs=ProportionalCostAssumptions(entry_cost_bps=0.,exit_cost_bps=0.,dividend_tax_pct=0.,note="synthetic")
    with pytest.raises(ValueError):
        inputs(costs=costs)
    with pytest.raises(ValueError):
        valuation_sensitivity(inputs().model_copy(update={"capitalization_cny":0.}))


def test_no_earnings_cases_still_supports_reverse_price_hurdle():
    result=valuation_sensitivity(inputs(terminal_profit_cases=(),reference_ttm_parent_profit_cny=None,
                                        reference_profit_basis_note=None))
    assert result["scenarios"]==[]
    assert result["current_implied_pe_on_reference_profit"] is None
    assert result["reverse_hurdles"][0]["required_profit_to_reference_ttm_x"] is None
