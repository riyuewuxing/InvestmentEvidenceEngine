import pytest
from test_joint_scenarios import ANCHOR, NOW, STOCK, inputs

from investment_evidence_engine.joint_portfolio_scenarios import (
    ExistingHoldingsState,
    OtherHoldingState,
    PortfolioScenarioInputs,
    conditional_portfolio_stress,
)
from investment_evidence_engine.portfolio_stress import StressPosition



def portfolio():
    return PortfolioScenarioInputs(initial_equity_cny=100000.,cash_cny=40000.,
        positions=(StressPosition(subject_id=STOCK.symbol,market_value_cny=40000.),
            StressPosition(subject_id="600001",market_value_cny=20000.)),
        state_assumptions=(
            ExistingHoldingsState(state_id="down",other_holdings=(OtherHoldingState(subject_id="600001",
                terminal_holding_return_pct=-10.,basis_note="synthetic other holding"),)),
            ExistingHoldingsState(state_id="up",other_holdings=(OtherHoldingState(subject_id="600001",
                terminal_holding_return_pct=10.,basis_note="synthetic other holding"),)),
        ))


def test_existing_candidate_mark_and_equal_cash_alternatives():
    result=conditional_portfolio_stress(ANCHOR,inputs(),portfolio(),evaluated_at=NOW)
    assert result["status"]=="CONDITIONAL_PORTFOLIO_STRESS_ONLY"
    down=result["states"][0]
    assert down["existing_holdings_terminal_mark_cny"]==38000.
    assert down["baseline_terminal_wealth_cny"]==78000.
    assert down["stock_terminal_wealth_cny"]==pytest.approx(73487.61)
    assert down["stock_minus_baseline_pp"]==pytest.approx(-4.51239)
    assert result["terminal_ranges"]["baseline"]["worst_stated_terminal_loss_pct"]==22.
    assert result["worst_stated_loss_differences_pp"]["stock_minus_baseline_loss_pp"]==pytest.approx(4.51239)
    assert not result["formal_marginal_portfolio_risk_estimated"]


def test_missing_states_other_holdings_and_cash_rejected():
    p=portfolio()
    x=inputs()
    for bad in (p.model_copy(update={"cash_cny":39999.}),
                p.model_copy(update={"state_assumptions":(p.state_assumptions[0],
                    p.state_assumptions[1].model_copy(update={"state_id":"other"}))}),
                p.model_copy(update={"state_assumptions":(p.state_assumptions[0],
                    p.state_assumptions[1].model_copy(update={"other_holdings":()}))})):
        with pytest.raises(ValueError):
            conditional_portfolio_stress(ANCHOR,x,bad,evaluated_at=NOW)
    with pytest.raises(ValueError,match="EXCEEDS"):
        conditional_portfolio_stress(ANCHOR,x.model_copy(update={"budget_cny":40001.}),p,evaluated_at=NOW)


def test_missing_cost_never_becomes_formal_risk():
    r=conditional_portfolio_stress(ANCHOR,inputs().model_copy(update={"etf_cost":None}),portfolio(),evaluated_at=NOW)
    assert r["status"]=="INCOMPLETE_STATED_STATES"
    assert r["terminal_ranges"]=={} and r["worst_stated_loss_differences_pp"] is None


def test_cash_return_same_in_baseline_and_unallocated_sleeves():
    x=inputs()
    state=x.states[0].model_copy(update={"cash_net_return_pct":2.})
    r=conditional_portfolio_stress(ANCHOR,x.model_copy(update={"states":(state,x.states[1])}),portfolio(),evaluated_at=NOW)
    assert r["states"][0]["baseline_terminal_wealth_cny"]==78800.
    assert r["states"][0]["unallocated_cash_terminal_cny"]==30600.


def test_cannot_supply_separate_return_for_held_candidate():
    p=portfolio()
    a=p.state_assumptions[0]
    a=a.model_copy(update={"other_holdings":a.other_holdings+(OtherHoldingState(subject_id=STOCK.symbol,
        terminal_holding_return_pct=5.,basis_note="inconsistent alternate stock state"),)})
    with pytest.raises(ValueError,match="COVERAGE"):
        conditional_portfolio_stress(ANCHOR,inputs(),p.model_copy(update={"state_assumptions":(a,p.state_assumptions[1])}),
                                     evaluated_at=NOW)
