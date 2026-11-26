"""Empirical fixed-holding-session references, not forward risk estimates.

The calendar must cover every date in the requested range and match the
versioned official holiday schedule. Both unadjusted close series must cover
exactly that session set; no silent intersection, no suspended-price fill.
Reported windows overlap and cannot be treated as independent trials.
Cash-distribution scenarios are conditional on an explicitly supplied event
list; missing corporate actions, splits, dividend taxes, payment timing,
execution friction and historical data vintage remain unverified.
"""
from __future__ import annotations

import math
from datetime import date, datetime
from statistics import median
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat

from .historical_reference import HistoricalCloseSeries
from .market_calendar import NOTICE_URLS, SCHEDULE_VERSION, CalendarObservation, check_calendar

HORIZONS = (1, 5, 20)
TAIL_PCT = 10


class CashDistribution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, str_strip_whitespace=True)
    subject_id: str = Field(pattern=r"^[0-9]{6}$")
    disclosed_date: date
    ex_date: date
    gross_cash_per_unit_cny: FiniteFloat = Field(gt=0)
    source_locator: str = Field(min_length=12, max_length=1024)


class CashDistributionInputs(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    coverage: Literal["EXPLICIT_EVENTS_NOT_EXHAUSTIVE"] = "EXPLICIT_EVENTS_NOT_EXHAUSTIVE"
    events: tuple[CashDistribution, ...] = Field(max_length=100)


def _validate_events(inputs: CashDistributionInputs, subjects: tuple[str, str],
                     sessions: tuple[date, ...]) -> tuple[dict, dict, list]:
    inputs = CashDistributionInputs.model_validate(inputs.model_dump())
    events = {symbol: {} for symbol in subjects}
    included, excluded = [], []
    seen = set()
    for item in inputs.events:
        key = (item.subject_id, item.ex_date)
        if item.subject_id not in subjects or item.disclosed_date > item.ex_date or key in seen:
            raise ValueError("DISTRIBUTION_IDENTITY_OR_DATE_CONFLICT")
        if not item.source_locator.startswith("https://"):
            raise ValueError("DISTRIBUTION_SOURCE_LOCATOR_INVALID")
        seen.add(key)
        # A later announced or later effective event must never change the
        # earlier historical window. A distribution at first close is excluded:
        # purchase at that close does not acquire prior record-date entitlement.
        if item.disclosed_date > sessions[-1] or item.ex_date > sessions[-1]:
            excluded.append(item.model_dump(mode="json") | {"reason":"AFTER_CUTOFF"})
            continue
        if item.ex_date <= sessions[0]:
            excluded.append(item.model_dump(mode="json") | {"reason":"AT_OR_BEFORE_ENTRY_CLOSE"})
            continue
        if item.ex_date not in sessions:
            raise ValueError("DISTRIBUTION_NOT_ON_VERIFIED_SESSION")
        events[item.subject_id][item.ex_date] = item.gross_cash_per_unit_cny
        included.append(item.model_dump(mode="json"))
    return events, {"included": included, "excluded": excluded, "coverage": inputs.coverage}, included


def _wealth(series: HistoricalCloseSeries, cash: dict[date, float]) -> list[float]:
    # Ex-date entitlement credited/reinvested at close is an explicit hypothetical
    # gross-return convention, not a realizable brokerage cashflow or NAV return.
    closes = series.closes
    values = [1.0]
    for previous, current in zip(closes[:-1], closes[1:]):
        factor = (current.close+cash.get(current.session, 0.0))/previous.close
        next_value = values[-1]*factor
        if not math.isfinite(next_value) or next_value <= 0:
            raise ValueError("NONFINITE_OR_NONPOSITIVE_WEALTH")
        values.append(next_value)
    return values


def _window_returns(values: list[float], horizon: int) -> list[float]:
    result = [(values[i+horizon]/values[i]-1)*100 for i in range(len(values)-horizon)]
    if not all(math.isfinite(x) for x in result):
        raise ValueError("NONFINITE_HOLDING_RETURN")
    return result


def _stats(returns: list[float]) -> dict:
    # Nearest rank empirical lower decile, and average of ceil(10% n)
    # worst observed returns. This is descriptive, not calibrated VaR/ES.
    ordered = sorted(returns)
    count = max(1, math.ceil(len(ordered)*TAIL_PCT/100))
    return {"median_pct": median(ordered), "lower_decile_pct": ordered[count-1],
        "worst_decile_mean_pct": math.fsum(ordered[:count])/count,
        "worst_pct": ordered[0], "best_pct": ordered[-1],
        "observed_loss_frequency_pct": sum(x<0 for x in ordered)*100/len(ordered),
        "tail_observations": count}


def _horizons(left: list[float], right: list[float]) -> list[dict]:
    result = []
    for horizon in HORIZONS:
        blocks = (len(left)-1)//horizon
        common = {"holding_sessions": horizon, "rolling_windows": len(left)-horizon,
            "disjoint_windows_upper_bound": blocks, "overlapping_windows": horizon>1,
            "independent_trials_verified": False}
        if len(left)<61 or blocks<10:
            result.append(common | {"status":"INSUFFICIENT_HISTORY", "required_min_closes":max(61,10*horizon+1)})
            continue
        a, b = _window_returns(left,horizon), _window_returns(right,horizon)
        excess = [x-y for x,y in zip(a,b)]
        result.append(common | {"status":"DESCRIPTIVE_ONLY", "candidate":_stats(a),
            "alternative":_stats(b), "candidate_minus_alternative":_stats(excess)})
    return result


def holding_period_reference(candidate: HistoricalCloseSeries, alternative: HistoricalCloseSeries,
                             calendar: CalendarObservation, *, first: date, last: date,
                             cutoff: datetime, distributions: CashDistributionInputs | None = None) -> dict:
    """Compute historical references after full calendar check, never forecast."""
    candidate = HistoricalCloseSeries.model_validate(candidate.model_dump())
    alternative = HistoricalCloseSeries.model_validate(alternative.model_dump())
    if (candidate.subject_id==alternative.subject_id or candidate.currency!="CNY"
            or alternative.currency!="CNY" or candidate.price_basis!="RAW_CLOSE"
            or alternative.price_basis!="RAW_CLOSE"):
        raise ValueError("RAW_PAIR_IDENTITY_OR_BASIS_INVALID")
    sessions = check_calendar(calendar, first=first, last=last, cutoff=cutoff)
    if any(tuple(x.session for x in series.closes)!=sessions for series in (candidate,alternative)):
        raise ValueError("PRICE_SESSION_COVERAGE_INCOMPLETE")
    raw_a, raw_b = _wealth(candidate,{}), _wealth(alternative,{})
    result = {"status":"HISTORICAL_HOLDING_REFERENCE_ONLY", "first_session":sessions[0].isoformat(),
        "last_session":sessions[-1].isoformat(), "session_count":len(sessions),
        "candidate_subject_id":candidate.subject_id, "alternative_subject_id":alternative.subject_id,
        "calendar_match":"BAOSTOCK_VS_REVIEWED_SSE_SZSE_ANNUAL_SCHEDULE",
        "calendar_observed_at":calendar.observed_at.isoformat(), "calendar_schedule_version":SCHEDULE_VERSION,
        "calendar_notice_urls":[url for year in range(first.year,last.year+1) for url in NOTICE_URLS[year]],
        "calendar_coverage_verified_against_observed_schedule":True,
        "raw_price_basis":"RAW_CLOSE_WITHOUT_DISTRIBUTIONS",
        "raw_price_windows":_horizons(raw_a,raw_b),
        "raw_full_window_pct":{"candidate":(raw_a[-1]-1)*100,"alternative":(raw_b[-1]-1)*100},
        "cash_scenario_status":"NOT_SUPPLIED", "corporate_action_coverage_verified":False,
        "historical_vintage_verified":False, "forward_probability_estimated":False,
        "future_net_return_estimated":False, "liquidity_cost_estimated":False,
        "marginal_portfolio_risk_estimated":False, "decision_authority":False,
        "research_only":True, "execution_allowed":False}
    if distributions is not None:
        event_map, audit, included = _validate_events(distributions,
            (candidate.subject_id,alternative.subject_id),sessions)
        # An empty list is not proof of zero corporate actions. Keep this
        # calculation conditional even if no listed event falls inside.
        a, b = _wealth(candidate,event_map[candidate.subject_id]), _wealth(alternative,event_map[alternative.subject_id])
        result.update(cash_scenario_status="CONDITIONAL_GROSS_EX_DATE_REINVESTMENT_ONLY",
            cash_scenario_basis="EXPLICIT_LIST_ONLY_BEFORE_TAX_NO_COST_NO_SPLIT_ADJUSTMENT",
            cash_scenario_event_audit=audit, cash_scenario_windows=_horizons(a,b),
            cash_full_window_pct={"candidate":(a[-1]-1)*100,"alternative":(b[-1]-1)*100},
            distribution_effects=[{"subject_id":event["subject_id"],"ex_date":event["ex_date"],
                "gross_cash_per_unit_cny":event["gross_cash_per_unit_cny"]} for event in included])
    return result
