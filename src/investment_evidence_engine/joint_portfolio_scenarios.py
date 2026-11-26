"""Conditional terminal portfolio stress on a common stated joint state set.

Existing holdings are marked at terminal value plus explicit net distributions,
not liquidated. Only the new equal-budget sleeve is hypothetically sold and
includes its assumed execution costs. No historical tail measure, probability,
future marginal risk estimate, account authentication, or trade authority.
"""
from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

from .joint_scenarios import JointAssumptions, PairPriceAnchor, joint_scenarios
from .portfolio_stress import StressPosition


def _d(value: float | int) -> Decimal:
    return Decimal(str(value))


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"),rounding=ROUND_HALF_UP)


class OtherHoldingState(BaseModel):
    model_config=ConfigDict(extra="forbid",frozen=True,strict=True,str_strip_whitespace=True)
    subject_id: str=Field(min_length=1,max_length=80)
    terminal_holding_return_pct: FiniteFloat=Field(ge=-100,le=10000)
    basis_note: str=Field(min_length=1,max_length=500)
    return_basis: Literal["MARK_TO_TERMINAL_VALUE_PLUS_AFTER_TAX_DISTRIBUTIONS_NO_SALE"]="MARK_TO_TERMINAL_VALUE_PLUS_AFTER_TAX_DISTRIBUTIONS_NO_SALE"


class ExistingHoldingsState(BaseModel):
    model_config=ConfigDict(extra="forbid",frozen=True,strict=True,str_strip_whitespace=True)
    state_id: str=Field(pattern=r"^[A-Za-z0-9_-]{1,50}$")
    other_holdings: tuple[OtherHoldingState,...]=Field(max_length=50)

    @model_validator(mode="after")
    def unique(self) -> ExistingHoldingsState:
        if len({item.subject_id for item in self.other_holdings})!=len(self.other_holdings):
            raise ValueError("DUPLICATE_OTHER_HOLDING_STATE")
        return self


class PortfolioScenarioInputs(BaseModel):
    model_config=ConfigDict(extra="forbid",frozen=True,strict=True)
    initial_equity_cny: FiniteFloat=Field(gt=0,le=1e13)
    cash_cny: FiniteFloat=Field(ge=0,le=1e13)
    positions: tuple[StressPosition,...]=Field(max_length=50)
    state_assumptions: tuple[ExistingHoldingsState,...]=Field(min_length=2,max_length=12)

    @model_validator(mode="after")
    def reconcile(self) -> PortfolioScenarioInputs:
        if len({p.subject_id for p in self.positions})!=len(self.positions):
            raise ValueError("DUPLICATE_EXISTING_HOLDING")
        if len({s.state_id for s in self.state_assumptions})!=len(self.state_assumptions):
            raise ValueError("DUPLICATE_EXISTING_STATE")
        amounts=[self.cash_cny,self.initial_equity_cny,*(p.market_value_cny for p in self.positions)]
        if any(_money(_d(value))!=_d(value) for value in amounts):
            raise ValueError("PORTFOLIO_CENT_PRECISION_INVALID")
        if _d(self.cash_cny)+sum((_d(p.market_value_cny) for p in self.positions),Decimal(0))!=_d(self.initial_equity_cny):
            raise ValueError("PORTFOLIO_EQUITY_NOT_RECONCILED")
        return self


def conditional_portfolio_stress(anchor: PairPriceAnchor, assumptions: JointAssumptions,
                                portfolio: PortfolioScenarioInputs,*,evaluated_at: datetime) -> dict:
    portfolio=PortfolioScenarioInputs.model_validate(portfolio.model_dump())
    assumptions=JointAssumptions.model_validate(assumptions.model_dump())
    anchor=PairPriceAnchor.model_validate(anchor.model_dump())
    budget=_d(assumptions.budget_cny)
    cash=_d(portfolio.cash_cny)
    equity=_d(portfolio.initial_equity_cny)
    if budget>cash:
        raise ValueError("JOINT_BUDGET_EXCEEDS_EXISTING_CASH")
    states={s.state_id:s for s in portfolio.state_assumptions}
    if set(states)!={s.state_id for s in assumptions.states}:
        raise ValueError("JOINT_EXISTING_STATE_COVERAGE_MISMATCH")
    stock,etf=anchor.stock.symbol,anchor.etf.symbol
    other_ids={p.subject_id for p in portfolio.positions}-{stock,etf}
    if any({p.subject_id for p in state.other_holdings}!=other_ids for state in states.values()):
        raise ValueError("JOINT_OTHER_HOLDING_COVERAGE_MISMATCH")
    sleeve=joint_scenarios(anchor,assumptions,evaluated_at=evaluated_at)
    rows=[]
    for state,computed in zip(assumptions.states,sleeve["states"]):
        common={"state_id":state.state_id}
        factor=None if state.cash_net_return_pct is None else 1+_d(state.cash_net_return_pct)/100
        if factor is None or any(computed[key].get("terminal_wealth_cny") is None for key in ("stock","etf","cash")):
            rows.append(common | {"status":"INCOMPLETE_SLEEVE_OR_CASH_ASSUMPTIONS"})
            continue
        marks={p.subject_id:1+_d(p.terminal_holding_return_pct)/100 for p in states[state.state_id].other_holdings}
        # A held candidate/alternative is driven by exactly the same price and
        # payout state as the new sleeve, never a separately supplied return.
        sp,ep=_d(anchor.stock_raw_close_cny),_d(anchor.etf_raw_close_cny)
        stock_payout=state.stock.after_tax_cash_per_initial_share_cny
        etf_payout=state.etf.after_tax_cash_per_initial_unit_cny
        if stock_payout is None or etf_payout is None:
            rows.append(common | {"status":"INCOMPLETE_HELD_PAYOUT_ASSUMPTIONS"})
            continue
        marks[stock]=(state.stock.price()+_d(stock_payout))/sp
        marks[etf]=(ep*(1+_d(state.etf.market_price_return_pct)/100)+_d(etf_payout))/ep
        held=sum((_money(_d(p.market_value_cny)*marks[p.subject_id]) for p in portfolio.positions),Decimal(0))
        # Same cent-rounded unallocated cash and envelope under all alternatives.
        # Avoid double rounding: define baseline as the same residual cash plus
        # the standalone cash alternative, not a separately rounded total.
        remaining=_money((cash-budget)*factor)
        base=held+remaining+_d(computed["cash"]["terminal_wealth_cny"])
        a=held+remaining+_d(computed["stock"]["terminal_wealth_cny"])
        b=held+remaining+_d(computed["etf"]["terminal_wealth_cny"])
        def ret(value):
            return float((value/equity-1)*100)
        rows.append(common | {"status":"CONDITIONAL_PORTFOLIO_STATE_ONLY",
            "existing_holdings_terminal_mark_cny":float(held),"unallocated_cash_terminal_cny":float(remaining),
            "baseline_terminal_wealth_cny":float(base),"stock_terminal_wealth_cny":float(a),
            "etf_terminal_wealth_cny":float(b),"baseline_return_pct":ret(base),
            "stock_return_pct":ret(a),"etf_return_pct":ret(b),
            "stock_minus_baseline_pp":float((a-base)/equity*100),
            "etf_minus_baseline_pp":float((b-base)/equity*100),
            "stock_minus_etf_pp":float((a-b)/equity*100)})
    ranges={}
    increments=None
    if all(row["status"]=="CONDITIONAL_PORTFOLIO_STATE_ONLY" for row in rows):
        for key in ("baseline","stock","etf"):
            vals=[row[key+"_return_pct"] for row in rows]
            ranges[key]={"worst_terminal_return_pct":min(vals),"best_terminal_return_pct":max(vals),
                         "worst_stated_terminal_loss_pct":max(0.,-min(vals))}
        loss={key:value["worst_stated_terminal_loss_pct"] for key,value in ranges.items()}
        increments={"stock_minus_baseline_loss_pp":loss["stock"]-loss["baseline"],
                    "etf_minus_baseline_loss_pp":loss["etf"]-loss["baseline"],
                    "stock_minus_etf_loss_pp":loss["stock"]-loss["etf"]}
    return {"status":"CONDITIONAL_PORTFOLIO_STRESS_ONLY" if increments is not None else "INCOMPLETE_STATED_STATES",
        "reference_session":anchor.reference_session.isoformat(),
        "horizon_end_calendar_date":sleeve["horizon_end_calendar_date"],
        "normalized_pair_sha256":anchor.normalized_pair_sha256,
        "initial_equity_cny":float(equity),"initial_cash_cny":float(cash),"equal_budget_cny":float(budget),
        "position_count":len(portfolio.positions),"states":rows,"terminal_ranges":ranges,
        "worst_stated_loss_differences_pp":increments,
        "scope_note":"EXISTING_MARKS_PLUS_NET_PAYOUTS_NEW_SLEEVE_ASSUMED_LIQUIDATION_NO_REBALANCE",
        "account_authentication_verified":False,"probability_estimated":False,
        "expected_return_estimated":False,"formal_marginal_portfolio_risk_estimated":False,
        "decision_authority":False,"research_only":True,"execution_allowed":False}
