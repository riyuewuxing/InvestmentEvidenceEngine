"""Equal-notional historical cash-substitution stress, not predictive risk.

Each overlapping historical window starts with the same hypothetical initial
market values. Positions are held without rebalancing until the window ends.
Cash is held nominally constant by explicit scenario assumption, not risk-free.
No corporate-action adjustments, costs, execution, allocation advice or PIT
admission are inferred. All price series must cover the exact complete calendar.
"""
from __future__ import annotations

import math
from datetime import date, datetime
from statistics import median
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

from .historical_reference import HistoricalCloseSeries
from .market_calendar import CalendarObservation, check_calendar


class StressPosition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    subject_id: str = Field(min_length=1,max_length=80)
    market_value_cny: FiniteFloat = Field(gt=0,le=1e13)


class PortfolioStressInputs(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    initial_equity_cny: FiniteFloat = Field(gt=0,le=1e13)
    cash_cny: FiniteFloat = Field(ge=0,le=1e13)
    notional_cny: FiniteFloat = Field(gt=0,le=1e13)
    positions: tuple[StressPosition,...] = Field(max_length=50)
    candidate_id: str = Field(min_length=1,max_length=80)
    alternative_id: str = Field(min_length=1,max_length=80)
    cash_policy: Literal["NOMINAL_CONSTANT_CASH_SCENARIO_NOT_RISK_FREE"] = "NOMINAL_CONSTANT_CASH_SCENARIO_NOT_RISK_FREE"

    @model_validator(mode="after")
    def reconcile(self) -> PortfolioStressInputs:
        ids=[p.subject_id for p in self.positions]
        if len(ids)!=len(set(ids)) or self.candidate_id==self.alternative_id:
            raise ValueError("POSITION_OR_ALTERNATIVE_IDENTITY_CONFLICT")
        if self.notional_cny>self.cash_cny:
            raise ValueError("NOTIONAL_EXCEEDS_CASH")
        if not math.isclose(math.fsum([self.cash_cny,*(p.market_value_cny for p in self.positions)]),
                            self.initial_equity_cny,rel_tol=0,abs_tol=0.011):
            raise ValueError("INITIAL_EQUITY_NOT_RECONCILED")
        return self


def _tail(returns: list[float]) -> dict:
    sorted_returns=sorted(returns)
    count=math.ceil(len(returns)/10)
    worst_mean=math.fsum(sorted_returns[:count])/count
    return {"median_pct":median(sorted_returns),"lower_decile_pct":sorted_returns[count-1],
            "worst_decile_mean_pct":worst_mean,"tail_loss_pct":max(0.,-worst_mean),
            "worst_pct":sorted_returns[0],"tail_observations":count}


def historical_cash_substitution_stress(inputs: PortfolioStressInputs,
        series: tuple[HistoricalCloseSeries,...], calendar: CalendarObservation, *,
        first: date, last: date, cutoff: datetime) -> dict:
    inputs=PortfolioStressInputs.model_validate(inputs.model_dump())
    sessions=check_calendar(calendar,first=first,last=last,cutoff=cutoff)
    required={inputs.candidate_id,inputs.alternative_id,*(p.subject_id for p in inputs.positions)}
    by_id={}
    for item in series:
        item=HistoricalCloseSeries.model_validate(item.model_dump())
        if item.subject_id in by_id:
            raise ValueError("DUPLICATE_PRICE_SERIES")
        if (item.currency!="CNY" or item.price_basis!="RAW_CLOSE"
                or tuple(row.session for row in item.closes)!=sessions):
            raise ValueError("PRICE_SESSION_OR_BASIS_MISMATCH")
        by_id[item.subject_id]=tuple(row.close for row in item.closes)
    if set(by_id)!=required:
        raise ValueError("PORTFOLIO_PRICE_COVERAGE_MISMATCH")
    windows=[]
    for horizon in (1,5,20):
        count=len(sessions)-horizon
        blocks=(len(sessions)-1)//horizon
        common={"holding_sessions":horizon,"rolling_windows":max(0,count),
                "disjoint_windows_upper_bound":blocks,"independent_trials_verified":False}
        if len(sessions)<61 or blocks<10:
            windows.append(common | {"status":"INSUFFICIENT_HISTORY",
                          "required_min_closes":max(61,10*horizon+1)})
            continue
        baseline, candidate, alternative=[],[],[]
        for i in range(count):
            change={key:values[i+horizon]/values[i]-1 for key,values in by_id.items()}
            existing=math.fsum(p.market_value_cny*change[p.subject_id] for p in inputs.positions)
            nums=[existing,existing+inputs.notional_cny*change[inputs.candidate_id],
                  existing+inputs.notional_cny*change[inputs.alternative_id]]
            returns=[(value/inputs.initial_equity_cny)*100 for value in nums]
            if not all(math.isfinite(value) for value in returns):
                raise ValueError("NONFINITE_STRESS_RESULT")
            baseline.append(returns[0])
            candidate.append(returns[1])
            alternative.append(returns[2])
        base,a,b=_tail(baseline),_tail(candidate),_tail(alternative)
        windows.append(common | {"status":"DESCRIPTIVE_ONLY","baseline":base,"candidate":a,"alternative":b,
            "candidate_minus_baseline_tail_loss_pp":a["tail_loss_pct"]-base["tail_loss_pct"],
            "alternative_minus_baseline_tail_loss_pp":b["tail_loss_pct"]-base["tail_loss_pct"],
            "candidate_minus_alternative_tail_loss_pp":a["tail_loss_pct"]-b["tail_loss_pct"]})
    return {"status":"HISTORICAL_CASH_SUBSTITUTION_STRESS_ONLY",
            "input_scope":"CALLER_PROVIDED_INITIAL_MARKET_VALUES_NOT_VERIFIED_ACCOUNT",
            "candidate_id":inputs.candidate_id,"alternative_id":inputs.alternative_id,
            "first_session":sessions[0].isoformat(),"last_session":sessions[-1].isoformat(),
            "initial_equity_cny":inputs.initial_equity_cny,"cash_cny":inputs.cash_cny,
            "equal_notional_cny":inputs.notional_cny,"position_count":len(inputs.positions),
            "cash_policy":inputs.cash_policy,"window_policy":"FIXED_INITIAL_VALUES_BUY_AND_HOLD_EACH_WINDOW",
            "price_basis":"RAW_CLOSE_WITHOUT_DISTRIBUTIONS_OR_SPLIT_ADJUSTMENT",
            "tail_definition":"MAX_0_NEGATIVE_MEAN_OF_CEIL_10PCT_WORST_WINDOW_RETURNS",
            "windows":windows,"corporate_action_coverage_verified":False,
            "historical_vintage_verified":False,"future_net_return_estimated":False,
            "forward_probability_estimated":False,"formal_marginal_portfolio_risk_estimated":False,
            "decision_authority":False,"research_only":True,"execution_allowed":False}
