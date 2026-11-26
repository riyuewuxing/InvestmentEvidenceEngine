"""Joint conditional stock / domestic equity ETF / cash alternatives.

Same reference session, horizon and all-in cash envelope in every state.
Stock earnings/PE/share-count or explicitly assumed terminal price; ETF
secondary-market price change plus separate distributions; cash cumulative
return. No probability weights, calibrated forecasts, trade, or admission.
The broker fees and future slippage are explicit assumptions, not observations.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, FiniteFloat, model_validator

from .cash_fees import CashFeeScenario, CommissionScenario, fee_scenario
from .historical_capture import SH, PublicSecurity, validate_window
from .market_calendar import scheduled_days

MODEL_VERSION = "JOINT_CASH_ALTERNATIVES_V1"
LOT_RULE_SOURCES = (
    "https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml",
    "https://edu.sse.com.cn/tib/qa/",
    "https://www.szse.cn/lawrules/rule/trade/current/t20260424_620190.html",
)
MAX_PRICE = Decimal("1000000")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, str_strip_whitespace=True)


def _d(value: float | int | str | Decimal) -> Decimal:
    return Decimal(str(value))


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _pct(value: Decimal, basis: Decimal) -> float:
    return float((value / basis - 1) * 100)


class PairPriceAnchor(_Strict):
    stock: PublicSecurity
    etf: PublicSecurity
    reference_session: date
    stock_raw_close_cny: FiniteFloat = Field(gt=0,le=1e6)
    etf_raw_close_cny: FiniteFloat = Field(gt=0,le=1e6)
    observed_at: AwareDatetime
    normalized_pair_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def scope(self) -> PairPriceAnchor:
        self.stock.prefixed
        self.etf.prefixed
        if self.stock.asset_type!="STOCK" or self.etf.asset_type!="ETF" or self.stock.symbol==self.etf.symbol:
            raise ValueError("ANCHOR_ASSET_SCOPE_INVALID")
        if (self.reference_session<date(2026,7,6) or self.reference_session>date(2026,11,26)
                or not scheduled_days(self.reference_session,self.reference_session)[0].is_trading_day):
            raise ValueError("ANCHOR_RULE_SESSION_UNSUPPORTED")
        validate_window(self.reference_session-timedelta(days=30),self.reference_session,self.observed_at)
        if _d(self.stock_raw_close_cny)%Decimal("0.01") or _d(self.etf_raw_close_cny)%Decimal("0.001"):
            raise ValueError("ANCHOR_PRICE_INCREMENT_INVALID")
        return self


class FrictionScenario(_Strict):
    commission: CommissionScenario
    entry_adverse_bps: FiniteFloat = Field(ge=0,le=2000)
    exit_adverse_bps: FiniteFloat = Field(ge=0,le=2000)
    basis_note: str = Field(min_length=1,max_length=500)
    schedule_policy: Literal["REFERENCE_DATE_FEE_SCHEDULE_ASSUMED_UNCHANGED"] = "REFERENCE_DATE_FEE_SCHEDULE_ASSUMED_UNCHANGED"


class StockTerminal(_Strict):
    terminal_profit_cny: FiniteFloat | None = Field(default=None,gt=0,le=1e14)
    terminal_pe: FiniteFloat | None = Field(default=None,gt=0,le=10000)
    terminal_share_count: int | None = Field(default=None,gt=0,le=10**13)
    explicit_terminal_price_cny: FiniteFloat | None = Field(default=None,ge=0,le=1e6)
    after_tax_cash_per_initial_share_cny: FiniteFloat | None = Field(default=None,ge=0,le=1e6)
    basis_note: str = Field(min_length=1,max_length=600)

    @model_validator(mode="after")
    def method(self) -> StockTerminal:
        earnings=(self.terminal_profit_cny,self.terminal_pe,self.terminal_share_count)
        if self.explicit_terminal_price_cny is None:
            if any(value is None for value in earnings):
                raise ValueError("STOCK_POSITIVE_EARNINGS_PE_AND_TERMINAL_SHARES_REQUIRED")
        elif any(value is not None for value in earnings):
            raise ValueError("STOCK_TERMINAL_METHODS_MUST_NOT_MIX")
        if self.price()>MAX_PRICE:
            raise ValueError("STOCK_TERMINAL_PRICE_OUTSIDE_MODEL")
        return self

    def price(self) -> Decimal:
        if self.explicit_terminal_price_cny is not None:
            return _d(self.explicit_terminal_price_cny)
        return _d(self.terminal_profit_cny)*_d(self.terminal_pe)/_d(self.terminal_share_count)


class ETFTerminal(_Strict):
    market_price_return_pct: FiniteFloat = Field(ge=-100,le=10000)
    after_tax_cash_per_initial_unit_cny: FiniteFloat | None = Field(default=None,ge=0,le=1e6)
    basis_note: str = Field(min_length=1,max_length=600)
    price_basis: Literal["EX_DISTRIBUTION_SECONDARY_MARKET_PRICE_RETURN_NET_OF_INTERNAL_FUND_COSTS"] = "EX_DISTRIBUTION_SECONDARY_MARKET_PRICE_RETURN_NET_OF_INTERNAL_FUND_COSTS"


class JointState(_Strict):
    state_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,50}$")
    rationale: str = Field(min_length=1,max_length=800)
    invalidator: str = Field(min_length=1,max_length=500)
    stock: StockTerminal
    etf: ETFTerminal
    cash_net_return_pct: FiniteFloat | None = Field(default=None,gt=-100,le=100)
    cash_basis_note: str | None = Field(default=None,min_length=1,max_length=500)

    @model_validator(mode="after")
    def cash_basis(self) -> JointState:
        if (self.cash_net_return_pct is None)!=(self.cash_basis_note is None):
            raise ValueError("CASH_RETURN_AND_NOTE_MUST_BE_PAIRED")
        return self


class JointAssumptions(_Strict):
    stock: PublicSecurity
    etf: PublicSecurity
    reference_session: date
    horizon_calendar_days: int = Field(gt=0,le=1095)
    budget_cny: FiniteFloat = Field(gt=0,le=1e8)
    basis_note: str = Field(min_length=1,max_length=800)
    etf_scope_note: str = Field(min_length=1,max_length=500)
    etf_kind: Literal["DOMESTIC_EQUITY_ETF_SECONDARY"] = "DOMESTIC_EQUITY_ETF_SECONDARY"
    stock_cost: FrictionScenario | None = None
    etf_cost: FrictionScenario | None = None
    states: tuple[JointState,...] = Field(min_length=2,max_length=12)
    unit_policy: Literal["UNCHANGED_INITIAL_UNITS_NO_SPLIT_OR_RIGHTS_ASSUMPTION"] = "UNCHANGED_INITIAL_UNITS_NO_SPLIT_OR_RIGHTS_ASSUMPTION"

    @model_validator(mode="after")
    def scope(self) -> JointAssumptions:
        self.stock.prefixed
        self.etf.prefixed
        if self.stock.asset_type!="STOCK" or self.etf.asset_type!="ETF" or self.stock.symbol==self.etf.symbol:
            raise ValueError("JOINT_ASSET_SCOPE_INVALID")
        if _money(_d(self.budget_cny))!=_d(self.budget_cny):
            raise ValueError("BUDGET_CENT_PRECISION_INVALID")
        if len({s.state_id for s in self.states})!=len(self.states):
            raise ValueError("DUPLICATE_JOINT_STATE")
        return self


def _lot(subject: PublicSecurity) -> tuple[int,int,int]:
    """Conservative ordinary auction single-order scenario; not eligibility."""
    if subject.asset_type=="ETF":
        return 100,100,1000000
    code=subject.symbol
    if code.startswith("688"):
        return 200,1,100000
    if code.startswith(("300","301")):
        return 100,100,300000
    if code.startswith(("600","601","603","605","000","001","002","003")):
        return 100,100,1000000
    raise ValueError("JOINT_ORDINARY_CASH_BOARD_UNSUPPORTED")


def _tick(subject: PublicSecurity) -> Decimal:
    return Decimal("0.01" if subject.asset_type=="STOCK" else "0.001")


def _fill(subject: PublicSecurity,price: Decimal,bps: float,*,buy: bool) -> Decimal:
    adverse=_d(bps)/10000
    return price.__mul__(1+adverse if buy else 1-adverse).quantize(
        _tick(subject),rounding=ROUND_CEILING if buy else ROUND_FLOOR)


def _fee(subject: PublicSecurity,day: date,notional: Decimal,cost: FrictionScenario,*,buy: bool) -> Decimal:
    if notional==0 and not buy:
        return Decimal(0)
    result=fee_scenario(CashFeeScenario(subject=subject,
        kind="DOMESTIC_A_STOCK" if subject.asset_type=="STOCK" else "DOMESTIC_EQUITY_ETF_SECONDARY",
        reference_session=day,entry_notional_cny=float(notional),exit_notional_cny=float(notional),
        entry_orders=1,exit_orders=1,commission=cost.commission))
    return _d(result["buy" if buy else "sell"]["explicit_fee_scenario_cny"])


def _entry(subject: PublicSecurity,day: date,price: Decimal,budget: Decimal,cost: FrictionScenario | None) -> dict:
    minimum,step,maximum=_lot(subject)
    if cost is None:
        return {"status":"COST_ASSUMPTION_MISSING"}
    fill=_fill(subject,price,cost.entry_adverse_bps,buy=True)
    # A single-order constraint; large residual stays cash rather than
    # pretending additional orders or liquidity. Binary search includes fees.
    def spend(units: int) -> tuple[Decimal,Decimal]:
        value=_money(fill*units)
        return value,_fee(subject,day,value,cost,buy=True)
    initial,fee=spend(minimum)
    if initial+fee>budget:
        return {"status":"NO_AFFORDABLE_MINIMUM_LOT","minimum_units":minimum,
                "minimum_conditional_cash_cny":float(initial+fee)}
    low,high=0,(maximum-minimum)//step
    while low<high:
        mid=(low+high+1)//2
        value,fee=spend(minimum+mid*step)
        if value+fee<=budget:
            low=mid
        else:
            high=mid-1
    units=minimum+low*step
    value,fee=spend(units)
    residual=budget-value-fee
    if residual<0:
        raise ValueError("ENTRY_BUDGET_RECONCILIATION_FAILURE")
    return {"status":"CONDITIONAL_ALLOCATION_ONLY","units":units,
        "reference_close_cny":float(price),"assumed_entry_price_cny":float(fill),
        "entry_notional_cny":float(value),"entry_explicit_fee_cny":float(fee),
        "residual_cash_cny":float(residual),"single_order_cap_reached":units==maximum}


def _terminal(subject: PublicSecurity,day: date,price: Decimal,payout: float | None,
              cash_factor: Decimal | None,entry: dict,cost: FrictionScenario | None,budget: Decimal) -> dict:
    common={"terminal_reference_price_cny":float(price)}
    if entry["status"]!="CONDITIONAL_ALLOCATION_ONLY" or cost is None:
        return common | {"status":entry["status"]}
    if payout is None or cash_factor is None:
        return common | {"status":"PAYOUT_OR_RESIDUAL_CASH_ASSUMPTION_MISSING"}
    fill=_fill(subject,price,cost.exit_adverse_bps,buy=False)
    units=entry["units"]
    sale=_money(fill*units)
    fee=_fee(subject,day,sale,cost,buy=False)
    if sale>0 and fee>sale:
        # Fee exceeds terminal proceeds: no financed sale assumed.
        return common | {"status":"EXIT_FEE_EXCEEDS_CONDITIONAL_PROCEEDS"}
    cash_paid=_money(_d(payout)*units)
    residual=_money(_d(entry["residual_cash_cny"])*cash_factor)
    wealth=sale-fee+cash_paid+residual
    return common | {"status":"CONDITIONAL_TERMINAL_WEALTH_ONLY","assumed_exit_price_cny":float(fill),
        "exit_notional_cny":float(sale),"exit_explicit_fee_cny":float(fee),
        "after_tax_cash_distributions_cny":float(cash_paid),"terminal_residual_cash_cny":float(residual),
        "terminal_wealth_cny":float(wealth),"conditional_net_return_pct":_pct(wealth,budget),
        "zero_recovery_no_sale_fee_assumed":sale==0}


def _hurdle(subject: PublicSecurity,day: date,payout: float,cash_factor: Decimal,entry: dict,
             cost: FrictionScenario,budget: Decimal,target: Decimal) -> float | None:
    """Smallest model tick for which conditional stock wealth reaches target.

    Fee rounding and adverse tick rounding are part of the inversion. No
    extrapolation above bounded price domain. Zero recovery is an explicit
    no-sale assumption; a positive sale with fee exceeding proceeds is invalid.
    """
    tick=_tick(subject)
    def enough(n: int) -> bool:
        row=_terminal(subject,day,tick*n,payout,cash_factor,entry,cost,budget)
        return row["status"]=="CONDITIONAL_TERMINAL_WEALTH_ONLY" and _d(row["terminal_wealth_cny"])>=target
    if enough(0):
        return 0.
    high=int(MAX_PRICE/tick)
    if not enough(high):
        return None
    low=1
    while low<high:
        mid=(low+high)//2
        if enough(mid):
            high=mid
        else:
            low=mid+1
    return float(tick*low)


def joint_scenarios(anchor: PairPriceAnchor, assumptions: JointAssumptions, *, evaluated_at: datetime) -> dict:
    anchor=PairPriceAnchor.model_validate(anchor.model_dump())
    assumptions=JointAssumptions.model_validate(assumptions.model_dump())
    if (evaluated_at.utcoffset() is None or anchor.observed_at>evaluated_at
            or (anchor.stock,anchor.etf,anchor.reference_session)!=(assumptions.stock,assumptions.etf,assumptions.reference_session)):
        raise ValueError("JOINT_ANCHOR_SCOPE_OR_TIME_MISMATCH")
    day=anchor.reference_session
    budget=_d(assumptions.budget_cny)
    sp,ep=_d(anchor.stock_raw_close_cny),_d(anchor.etf_raw_close_cny)
    se=_entry(anchor.stock,day,sp,budget,assumptions.stock_cost)
    ee=_entry(anchor.etf,day,ep,budget,assumptions.etf_cost)
    rows=[]
    for state in assumptions.states:
        stock_price=state.stock.price()
        etf_price=ep*(1+_d(state.etf.market_price_return_pct)/100)
        if etf_price>MAX_PRICE:
            raise ValueError("ETF_TERMINAL_PRICE_OUTSIDE_MODEL")
        factor=None if state.cash_net_return_pct is None else 1+_d(state.cash_net_return_pct)/100
        cash_wealth=None if factor is None else _money(budget*factor)
        stock=_terminal(anchor.stock,day,stock_price,state.stock.after_tax_cash_per_initial_share_cny,
            factor,se,assumptions.stock_cost,budget)
        etf=_terminal(anchor.etf,day,etf_price,state.etf.after_tax_cash_per_initial_unit_cny,
            factor,ee,assumptions.etf_cost,budget)
        stock["conditional_price_return_pct"]=_pct(stock_price,sp)
        etf["conditional_price_return_pct"]=_pct(etf_price,ep)
        sn=stock.get("conditional_net_return_pct")
        en=etf.get("conditional_net_return_pct")
        cn=None if cash_wealth is None else _pct(cash_wealth,budget)
        hurdle={}
        if sn is not None and factor is not None and assumptions.stock_cost is not None:
            targets={"cash":cash_wealth,"etf":etf.get("terminal_wealth_cny")}
            for key,target in targets.items():
                if target is None:
                    continue
                price=_hurdle(anchor.stock,day,state.stock.after_tax_cash_per_initial_share_cny,
                    factor,se,assumptions.stock_cost,budget,_d(target))
                profit=None
                if price is not None and state.stock.terminal_pe is not None:
                    profit=float(_d(price)*state.stock.terminal_share_count/_d(state.stock.terminal_pe))
                hurdle[key]={"required_terminal_reference_price_cny":price,
                    "required_terminal_profit_cny_at_state_pe_and_shares":profit,
                    "target_terminal_wealth_cny":float(target)}
        rows.append({"state_id":state.state_id,"rationale":state.rationale,"invalidator":state.invalidator,
            "stock":stock,"etf":etf,"cash":{"terminal_wealth_cny":None if cash_wealth is None else float(cash_wealth),
                                         "conditional_net_return_pct":cn},
            "stock_minus_etf_pp":None if sn is None or en is None else sn-en,
            "stock_minus_cash_pp":None if sn is None or cn is None else sn-cn,
            "stock_terminal_hurdles":hurdle})
    summary={}
    for key in ("stock","etf","cash"):
        values=[row[key].get("conditional_net_return_pct") for row in rows]
        if any(x is None for x in values):
            summary[key]={"status":"INCOMPLETE_STATED_STATES"}
        else:
            summary[key]={"status":"STATED_STATES_ONLY","worst_terminal_return_pct":min(values),
                "best_terminal_return_pct":max(values),"worst_terminal_loss_pct":max(0.,-min(values))}
    dominance={}
    for other in ("etf","cash"):
        differences=[row["stock_minus_"+other+"_pp"] for row in rows]
        if any(x is None for x in differences):
            dominance[other]="NOT_COMPARABLE_ALL_STATES"
        elif all(x>=0 for x in differences) and any(x>0 for x in differences):
            dominance[other]="STOCK_AT_LEAST_AS_HIGH_IN_ALL_STATED_STATES"
        elif all(x<=0 for x in differences) and any(x<0 for x in differences):
            dominance[other]="ALTERNATIVE_AT_LEAST_AS_HIGH_IN_ALL_STATED_STATES"
        elif all(x==0 for x in differences):
            dominance[other]="TIED_IN_ALL_STATED_STATES"
        else:
            dominance[other]="STATE_DEPENDENT"
    return {"status":"JOINT_CONDITIONAL_RESEARCH_ONLY","model_version":MODEL_VERSION,
        "anchor":anchor.model_dump(mode="json"),"assumptions":assumptions.model_dump(mode="json"),
        "evaluated_at":evaluated_at.astimezone(SH).isoformat(),
        "horizon_end_calendar_date":(day+timedelta(days=assumptions.horizon_calendar_days)).isoformat(),
        "lot_rule_sources":list(LOT_RULE_SOURCES),"stock_entry":se,"etf_entry":ee,"states":rows,
        "terminal_ranges":summary,"stated_state_dominance":dominance,
        "scope_note":"NO_REINVESTMENT_OF_DISTRIBUTIONS_NO_INTERMEDIATE_PATH_NO_CORPORATE_UNIT_CHANGES",
        "probabilities_estimated":False,"expected_return_estimated":False,
        "downside_probability_estimated":False,"path_drawdown_estimated":False,
        "actual_broker_fee_verified":False,"actual_fill_verified":False,"formal_liquidity_cost_estimated":False,
        "formal_comparison_eligible":False,"decision_authority":False,"research_only":True,"execution_allowed":False}
