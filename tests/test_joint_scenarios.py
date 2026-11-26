from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from investment_evidence_engine.cash_fees import CommissionScenario
from investment_evidence_engine.historical_capture import PublicSecurity
from investment_evidence_engine.joint_scenarios import (
    ETFTerminal,
    FrictionScenario,
    JointAssumptions,
    JointState,
    PairPriceAnchor,
    StockTerminal,
    joint_scenarios,
)

SH=ZoneInfo("Asia/Shanghai")
NOW=datetime(2026,11,26,13,40,tzinfo=SH)
DAY=date(2026,11,25)
STOCK=PublicSecurity(symbol="600000",asset_type="STOCK")
ETF=PublicSecurity(symbol="510050",asset_type="ETF")
ANCHOR=PairPriceAnchor(stock=STOCK,etf=ETF,reference_session=DAY,
    stock_raw_close_cny=10.,etf_raw_close_cny=2.,observed_at=NOW,normalized_pair_sha256="a"*64)
COST=FrictionScenario(commission=CommissionScenario(inclusive_rate_bps=3.,
    minimum_per_order_cny=5.,note="synthetic"),entry_adverse_bps=0.,exit_adverse_bps=0.,
    basis_note="zero assumed friction for a transparent arithmetic test")


def inputs():
    def state(id,profit,etf):
        return JointState(state_id=id,rationale="synthetic joint state",invalidator="synthetic invalidator",
            stock=StockTerminal(terminal_profit_cny=profit,terminal_pe=10.,terminal_share_count=1000000,
                after_tax_cash_per_initial_share_cny=0.,basis_note="synthetic EPS and PE"),
            etf=ETFTerminal(market_price_return_pct=etf,after_tax_cash_per_initial_unit_cny=0.,
                basis_note="synthetic ETF price net of internal fees"),
            cash_net_return_pct=0.,cash_basis_note="nominal cash held unchanged")
    return JointAssumptions(stock=STOCK,etf=ETF,reference_session=DAY,horizon_calendar_days=365,
        budget_cny=10000.,basis_note="synthetic all-in cash envelope",etf_scope_note="domestic equity fixture",
        stock_cost=COST,etf_cost=COST,states=(state("down",500000.,-10.),state("up",1500000.,10.)))


def test_equal_all_in_budget_and_conditional_ranges():
    r=joint_scenarios(ANCHOR,inputs(),evaluated_at=NOW)
    assert r["stock_entry"]["units"]==900
    assert r["stock_entry"]["entry_explicit_fee_cny"]==5.09
    assert r["stock_entry"]["residual_cash_cny"]==994.91
    assert r["etf_entry"]["units"]==4900
    assert r["etf_entry"]["residual_cash_cny"]==195.
    down,up=r["states"]
    assert down["stock"]["terminal_reference_price_cny"]==5.
    assert down["stock"]["terminal_wealth_cny"]==pytest.approx(5487.61)
    assert up["stock"]["conditional_price_return_pct"]==50.
    assert down["stock_minus_cash_pp"]<0<up["stock_minus_cash_pp"]
    assert r["terminal_ranges"]["stock"]["worst_terminal_loss_pct"]==pytest.approx(45.1239)
    assert r["stated_state_dominance"]["etf"]=="STATE_DEPENDENT"
    assert not r["expected_return_estimated"] and not r["formal_comparison_eligible"]


def test_reverse_hurdle_accounts_for_discrete_fees():
    r=joint_scenarios(ANCHOR,inputs(),evaluated_at=NOW)
    hurdle=r["states"][0]["stock_terminal_hurdles"]["cash"]
    assert hurdle["required_terminal_reference_price_cny"]==10.02
    assert hurdle["required_terminal_profit_cny_at_state_pe_and_shares"]==1002000.


def test_missing_cost_or_cash_does_not_create_net_or_dominance():
    r=joint_scenarios(ANCHOR,inputs().model_copy(update={"stock_cost":None}),evaluated_at=NOW)
    assert r["stock_entry"]["status"]=="COST_ASSUMPTION_MISSING"
    assert r["states"][0]["stock"]["conditional_price_return_pct"]==-50.
    assert r["states"][0]["stock_minus_etf_pp"] is None
    assert r["stated_state_dominance"]["etf"]=="NOT_COMPARABLE_ALL_STATES"
    x=inputs()
    state=x.states[0].model_copy(update={"cash_net_return_pct":None,"cash_basis_note":None})
    r=joint_scenarios(ANCHOR,x.model_copy(update={"states":(state,x.states[1])}),evaluated_at=NOW)
    assert r["states"][0]["stock"]["status"]=="PAYOUT_OR_RESIDUAL_CASH_ASSUMPTION_MISSING"
    assert r["terminal_ranges"]["stock"]["status"]=="INCOMPLETE_STATED_STATES"


def test_no_affordable_stock_lot_not_cash_substitute():
    r=joint_scenarios(ANCHOR,inputs().model_copy(update={"budget_cny":500.}),evaluated_at=NOW)
    assert r["stock_entry"]["status"]=="NO_AFFORDABLE_MINIMUM_LOT"
    assert r["states"][0]["stock_minus_cash_pp"] is None


def test_explicit_zero_recovery_and_unknown_payout():
    x=inputs()
    state=x.states[0].model_copy(update={"stock":StockTerminal(explicit_terminal_price_cny=0.,
        after_tax_cash_per_initial_share_cny=0.,basis_note="synthetic zero recovery")})
    r=joint_scenarios(ANCHOR,x.model_copy(update={"states":(state,x.states[1])}),evaluated_at=NOW)
    assert r["states"][0]["stock"]["zero_recovery_no_sale_fee_assumed"]
    assert r["states"][0]["stock"]["terminal_wealth_cny"]==994.91
    state=state.model_copy(update={"stock":state.stock.model_copy(update={"after_tax_cash_per_initial_share_cny":None})})
    r=joint_scenarios(ANCHOR,x.model_copy(update={"states":(state,x.states[1])}),evaluated_at=NOW)
    assert "conditional_net_return_pct" not in r["states"][0]["stock"]


def test_reject_bad_identity_chronology_methods_and_duplicate_states():
    x=inputs()
    for changes in ({"reference_session":date(2026,11,24)},
                    {"states":(x.states[0],x.states[0])},{"budget_cny":100.001}):
        with pytest.raises(ValueError):
            joint_scenarios(ANCHOR,x.model_copy(update=changes),evaluated_at=NOW)
    with pytest.raises(ValueError):
        StockTerminal(terminal_profit_cny=100.,terminal_pe=10.,terminal_share_count=100,
            explicit_terminal_price_cny=1.,basis_note="mixed")
    with pytest.raises(ValueError):
        joint_scenarios(ANCHOR,x,evaluated_at=datetime(2026,11,25,13,tzinfo=SH))


def test_star_minimum_and_tick_slippage():
    star=PublicSecurity(symbol="688001",asset_type="STOCK")
    a=ANCHOR.model_copy(update={"stock":star})
    x=inputs().model_copy(update={"stock":star,"budget_cny":2010.})
    r=joint_scenarios(a,x,evaluated_at=NOW)
    assert r["stock_entry"]["units"]==200
    assert r["stock_entry"]["residual_cash_cny"]==4.98
    changed=x.model_copy(update={"stock_cost":COST.model_copy(update={"entry_adverse_bps":1.})})
    r=joint_scenarios(a,changed,evaluated_at=NOW)
    assert r["stock_entry"]["assumed_entry_price_cny"]==10.01
