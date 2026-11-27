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
from decimal import Decimal, localcontext
from statistics import median
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

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


class ShareCashDistribution(BaseModel):
    """One explicit combined/split/cash shareholder event, not issuer cancellation."""
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, str_strip_whitespace=True)
    action_id: str = Field(min_length=1, max_length=120)
    subject_id: str = Field(pattern=r"^[0-9]{6}$")
    disclosed_date: date
    record_date: date
    ex_date: date
    post_units_numerator: int = Field(gt=0, le=1000000)
    pre_units_denominator: int = Field(gt=0, le=1000000)
    gross_cash_per_old_unit_cny: str = Field(pattern=r"^(0|[1-9][0-9]{0,6})(\.[0-9]{1,8})?$")
    source_locator: str = Field(min_length=12, max_length=1024)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def check_terms(self) -> ShareCashDistribution:
        if not self.disclosed_date <= self.record_date < self.ex_date:
            raise ValueError("SHARE_CASH_EVENT_DATE_ORDER")
        if (self.post_units_numerator == self.pre_units_denominator
                and Decimal(self.gross_cash_per_old_unit_cny) == 0):
            raise ValueError("SHARE_CASH_NOOP_EVENT")
        route = urlsplit(self.source_locator)
        if (route.scheme != "https" or not route.hostname or route.username
                or route.password or route.fragment):
            raise ValueError("SHARE_CASH_SOURCE_LOCATOR")
        return self


class ShareCashDistributionInputs(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    coverage: Literal["EXPLICIT_EVENTS_NOT_EXHAUSTIVE"] = "EXPLICIT_EVENTS_NOT_EXHAUSTIVE"
    events: tuple[ShareCashDistribution, ...] = Field(max_length=100)


def share_cash_ex_factor(prior: Decimal, current: Decimal, event: ShareCashDistribution) -> Decimal:
    """Gross ex-close reinvestment factor per old share; raw CNY prices only.

    Caller must validate event/window binding and price basis. No claim about
    payment, fractional share rounding, subscription, fees, or source vintage.
    """
    event = ShareCashDistribution.model_validate(event.model_dump())
    if any(type(v) is not Decimal or not v.is_finite() or not 0 < v <= 1000000
           for v in (prior, current)):
        raise ValueError("SHARE_CASH_PRICE_INVALID")
    with localcontext() as ctx:
        ctx.prec = 48
        return (current * event.post_units_numerator / event.pre_units_denominator
                + Decimal(event.gross_cash_per_old_unit_cny)) / prior


def _validate_share_cash_events(inputs: ShareCashDistributionInputs, subjects: tuple[str, str],
                                sessions: tuple[date, ...]) -> tuple[dict, dict]:
    inputs = ShareCashDistributionInputs.model_validate(inputs.model_dump())
    events = {symbol: {} for symbol in subjects}
    seen_ids, seen_days = set(), set()
    included, excluded = [], []
    for event in inputs.events:
        key = (event.subject_id, event.ex_date)
        if event.subject_id not in subjects or event.action_id in seen_ids or key in seen_days:
            raise ValueError("SHARE_CASH_IDENTITY_OR_DUPLICATE")
        seen_ids.add(event.action_id)
        seen_days.add(key)
        row = event.model_dump(mode="json")
        if event.ex_date > sessions[-1]:
            excluded.append(row | {"reason": "AFTER_CUTOFF"})
        elif event.ex_date <= sessions[0]:
            excluded.append(row | {"reason": "AT_OR_BEFORE_ENTRY_CLOSE"})
        else:
            if event.ex_date not in sessions or sessions[sessions.index(event.ex_date)-1] != event.record_date:
                raise ValueError("SHARE_CASH_RECORD_EX_SESSION_MISMATCH")
            events[event.subject_id][event.ex_date] = event
            included.append(row)
    return events, {"included": included, "excluded": excluded, "coverage": inputs.coverage}


def _share_cash_wealth(series: HistoricalCloseSeries, events: dict[date, ShareCashDistribution]) -> list[float]:
    if series.price_basis != "RAW_CLOSE" or series.currency != "CNY":
        raise ValueError("SHARE_CASH_RAW_CNY_REQUIRED")
    values = [1.0]
    for previous, current in zip(series.closes[:-1], series.closes[1:]):
        event = events.get(current.session)
        factor = (float(share_cash_ex_factor(Decimal(str(previous.close)), Decimal(str(current.close)), event))
                  if event is not None else current.close / previous.close)
        value = values[-1] * factor
        if not math.isfinite(value) or value <= 0:
            raise ValueError("SHARE_CASH_WEALTH_INVALID")
        values.append(value)
    return values


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
                             cutoff: datetime, distributions: CashDistributionInputs | None = None,
                             share_cash_distributions: ShareCashDistributionInputs | None = None) -> dict:
    """Compute historical references after full calendar check, never forecast."""
    if distributions is not None and share_cash_distributions is not None:
        raise ValueError("SHARE_CASH_AND_CASH_SCENARIOS_MUTUALLY_EXCLUSIVE")
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
    if share_cash_distributions is not None:
        event_map, audit = _validate_share_cash_events(
            share_cash_distributions, (candidate.subject_id, alternative.subject_id), sessions)
        a = _share_cash_wealth(candidate, event_map[candidate.subject_id])
        b = _share_cash_wealth(alternative, event_map[alternative.subject_id])
        result.update(share_cash_scenario_status="CONDITIONAL_GROSS_EX_CLOSE_REINVESTMENT_ONLY",
            share_cash_scenario_basis="RAW_EXPLICIT_SHARE_RATIO_AND_CASH_PER_OLD_UNIT_ONCE",
            share_cash_event_audit=audit, share_cash_scenario_windows=_horizons(a, b),
            share_cash_full_window_pct={"candidate": (a[-1]-1)*100, "alternative": (b[-1]-1)*100},
            share_cash_actual_credit_verified=False, share_cash_original_bytes_verified=False,
            share_cash_fractional_rounding_verified=False, share_cash_reinvestment_executable=False,
            share_cash_tax_and_cost_verified=False, share_cash_total_return_certified=False)
    return result
