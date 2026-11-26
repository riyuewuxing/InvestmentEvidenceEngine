"""Real public control: calendar coverage, ex-date handling, horizon statistics.

The public test uses fixed symbols unrelated to private accounts. Only derived
statistics and normalized receipt hashes are printed. Cash event locators are
public issuer notices manually read; the event list is NOT exhaustive.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from investment_evidence_engine.cash_fees import CommissionScenario
from investment_evidence_engine.historical_capture import PublicSecurity, observe_pair
from investment_evidence_engine.historical_receipt import (
    HistoricalCaptureFailure,
    HistoricalReceipt,
    load_receipt,
    persist_receipt,
)
from investment_evidence_engine.holding_risk import CashDistribution, CashDistributionInputs
from investment_evidence_engine.joint_portfolio_scenarios import (
    ExistingHoldingsState,
    PortfolioScenarioInputs,
    conditional_portfolio_stress,
)
from investment_evidence_engine.joint_scenario_receipt import (
    JointScenarioReceipt,
    load_joint_receipt,
    load_pair_anchor,
    persist_joint_receipt,
)
from investment_evidence_engine.joint_scenarios import (
    ETFTerminal,
    FrictionScenario,
    JointAssumptions,
    JointState,
    StockTerminal,
)
from investment_evidence_engine.market_calendar import acquire_calendar
from investment_evidence_engine.portfolio_stress import (
    PortfolioStressInputs,
    StressPosition,
    historical_cash_substitution_stress,
)

START=date(2025,11,25)
END=date(2026,11,25)
SH=ZoneInfo("Asia/Shanghai")


def event(subject, disclosed, effective, amount, locator):
    return CashDistribution(subject_id=subject,disclosed_date=date.fromisoformat(disclosed),
        ex_date=date.fromisoformat(effective),gross_cash_per_unit_cny=amount,source_locator=locator)


def main() -> int:
    candidate=PublicSecurity(symbol="600519",asset_type="STOCK")
    alternative=PublicSecurity(symbol="510050",asset_type="ETF")
    summary,sources=observe_pair(candidate,alternative,START,END,providers=("sina","baostock","tencent"))
    if not sources or summary["status"]!="OBSERVED_REFERENCE_ONLY":
        print(json.dumps({"status":"BLOCKED","price_observation":summary}))
        return 2
    try:
        cal=acquire_calendar(START,END)
    except (ValueError,OSError) as exc:
        print(json.dumps({"status":"BLOCKED","calendar_error":str(exc)[:160],"decision_authority":False}))
        return 2
    events=CashDistributionInputs(events=(
        event("600519","2025-12-11","2025-12-19",23.957,
              "https://static.cninfo.com.cn/finalpage/2025-12-11/1224867074.PDF#page=1"),
        event("600519","2026-06-22","2026-06-26",28.02423,
              "https://static.cninfo.com.cn/finalpage/2026-06-22/1225379934.PDF#page=1"),
        event("510050","2025-12-10","2025-12-17",0.08,
              "https://big5.sse.com.cn/site/cht/www.sse.com.cn/disclosure/fund/announcement/c/new/2025-12-10/510050_20251210_C3NC.pdf#page=1"),
        event("510050","2026-11-25","2026-12-02",0.052,
              "https://www.sse.com.cn/disclosure/fund/announcement/c/new/2026-11-25/510050_20261125_6HA6.pdf#page=1"),
    ))
    receipt=HistoricalReceipt(schema_version="2",candidate=candidate,alternative=alternative,
        first_requested=START,last_completed=END,observed_at=datetime.now(SH),
        akshare_version=version("akshare"),attempted_providers=tuple(summary["attempted_providers"]),
        failures=tuple(HistoricalCaptureFailure.model_validate(f) for f in summary["failures"]),
        series=sources,calendar=cal,distributions=events)
    with TemporaryDirectory() as temp:
        digest, computed=persist_receipt(Path(temp),receipt)
        loaded=load_receipt(Path(temp),candidate,alternative,END,now=datetime.now(SH))
        assert loaded["holding_reference"]==computed["holding_reference"]
        assert loaded["normalized_observation_sha256"]==digest
        risk=loaded["holding_reference"]
        if risk["status"]!="HISTORICAL_HOLDING_REFERENCE_ONLY":
            print(json.dumps({"status":"BLOCKED","holding_reference":risk,"crosscheck":loaded["crosscheck"]}))
            return 2
        assert len(risk["cash_scenario_event_audit"]["included"])==3
        assert len(risk["cash_scenario_event_audit"]["excluded"])==1
        assert risk["cash_scenario_event_audit"]["excluded"][0]["reason"]=="AFTER_CUTOFF"
        assert risk["cash_full_window_pct"]["candidate"]>risk["raw_full_window_pct"]["candidate"]
        assert risk["cash_full_window_pct"]["alternative"]>risk["raw_full_window_pct"]["alternative"]
        assert risk["raw_price_windows"][-1]["status"]=="DESCRIPTIVE_ONLY"
        assert not risk["corporate_action_coverage_verified"]
        assert not risk["historical_vintage_verified"] and not risk["decision_authority"]
        # Independent public synthetic account; no private positions or account IDs.
        selected=tuple(next(s for s in receipt.series if s.subject_id==symbol)
                       for symbol in (candidate.symbol,alternative.symbol))
        stress=historical_cash_substitution_stress(PortfolioStressInputs(
            initial_equity_cny=100000.,cash_cny=40000.,notional_cny=20000.,
            positions=(StressPosition(subject_id=candidate.symbol,market_value_cny=60000.),),
            candidate_id=candidate.symbol,alternative_id=alternative.symbol),
            selected,cal,first=START,last=END,cutoff=receipt.observed_at)
        assert stress["windows"][-1]["status"]=="DESCRIPTIVE_ONLY"
        assert not stress["decision_authority"]
        # The prices are observed; every future outcome is a fixed synthetic
        # sensitivity. No private cases, account identifiers or forecasts.
        clock=datetime.now(SH)
        anchor=load_pair_anchor(Path(temp),candidate,alternative,END,now=clock)
        friction=FrictionScenario(commission=CommissionScenario(inclusive_rate_bps=3.,
            minimum_per_order_cny=5.,note="synthetic public terms"),entry_adverse_bps=5.,
            exit_adverse_bps=5.,basis_note="synthetic adverse fill, not an observed spread or impact")
        assumptions=JointAssumptions(stock=candidate,etf=alternative,reference_session=END,
            horizon_calendar_days=365,budget_cny=500000.,basis_note="fixed synthetic cash envelope",
            etf_scope_note="public domestic equity ETF control",stock_cost=friction,etf_cost=friction,
            states=tuple(JointState(state_id=key,rationale="synthetic price sensitivity",
                invalidator="not a forecast or actual investment thesis",
                stock=StockTerminal(explicit_terminal_price_cny=anchor.stock_raw_close_cny*(1+s_pct/100),
                    after_tax_cash_per_initial_share_cny=0.,basis_note="synthetic terminal price multiplier"),
                etf=ETFTerminal(market_price_return_pct=e_pct,after_tax_cash_per_initial_unit_cny=0.,
                    basis_note="synthetic ex-distribution market price return"),
                cash_net_return_pct=0.,cash_basis_note="synthetic nominal cash, not risk-free")
                for key,s_pct,e_pct in (("down",-20.,-10.),("up",15.,10.))))
        frozen=JointScenarioReceipt(anchor=anchor,assumptions=assumptions,recorded_at=clock,
                                    expires_at=clock+timedelta(hours=1))
        scenario_dir=Path(temp)/"scenario"
        joint_sha,expected=persist_joint_receipt(scenario_dir,frozen)
        joint=load_joint_receipt(scenario_dir,anchor,now=datetime.now(SH))
        assert joint["scenario_receipt_sha256"]==joint_sha and joint["scenario_receipt_rehashed"]
        assert joint["states"]==expected["states"]
        assert all(row["stock"]["status"]=="CONDITIONAL_TERMINAL_WEALTH_ONLY" and
                   row["etf"]["status"]=="CONDITIONAL_TERMINAL_WEALTH_ONLY" for row in joint["states"])
        assert not joint["formal_comparison_eligible"] and not joint["expected_return_estimated"]
        future_portfolio=conditional_portfolio_stress(anchor,assumptions,
            PortfolioScenarioInputs(initial_equity_cny=1000000.,cash_cny=600000.,
                positions=(StressPosition(subject_id=candidate.symbol,market_value_cny=400000.),),
                state_assumptions=tuple(ExistingHoldingsState(state_id=x.state_id,other_holdings=())
                                        for x in assumptions.states)),evaluated_at=clock)
        assert future_portfolio["status"]=="CONDITIONAL_PORTFOLIO_STRESS_ONLY"
        assert not future_portfolio["formal_marginal_portfolio_risk_estimated"]
        print(json.dumps({"joint_scenario_control":joint,"synthetic_forward_portfolio_stress":future_portfolio}))
        print(json.dumps({"status":"OBSERVED_REFERENCE_ONLY","crosscheck":loaded["crosscheck"],
            "normalized_receipt_sha256":digest,"normalized_receipt_rehash":"MATCH",
            "observed_at":loaded["observed_at"],"candidate_providers":loaded["candidate_providers"],
            "alternative_providers":loaded["alternative_providers"],"failures":loaded["failures"],
            "holding_reference":risk,"synthetic_portfolio_stress":stress}))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
