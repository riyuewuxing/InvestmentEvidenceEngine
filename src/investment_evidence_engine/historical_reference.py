"""Aligned historical price reference; not a prediction or evidence admission.

Only same-date, same-currency, same-price-basis observations are comparable.
No implicit inner join, forward fill, annualization, risk-free cash proxy,
portfolio claim, or assumed transaction cost. Dates are observed sessions,
not proof of an independently verified exchange calendar.
"""
from __future__ import annotations

import math
from datetime import date
from statistics import correlation, stdev
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator


class DailyClose(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    session: date
    close: FiniteFloat = Field(gt=0)


class HistoricalCloseSeries(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, str_strip_whitespace=True)
    subject_id: str = Field(min_length=1)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    price_basis: Literal["RAW_CLOSE", "PROVIDER_ADJUSTED_CLOSE_NOT_VINTAGE_VERIFIED"]
    source_label: str = Field(min_length=1)
    closes: tuple[DailyClose, ...] = Field(min_length=21, max_length=756)

    @model_validator(mode="after")
    def ordered_unique(self) -> HistoricalCloseSeries:
        dates = tuple(x.session for x in self.closes)
        if dates != tuple(sorted(set(dates))):
            raise ValueError("close sessions must be strictly increasing and unique")
        return self


class HistoricalPriceStatistics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    price_change_pct: FiniteFloat
    daily_sample_sd_pct: FiniteFloat = Field(ge=0)
    maximum_close_drawdown_pct: FiniteFloat = Field(ge=0)
    worst_daily_change_pct: FiniteFloat
    best_daily_change_pct: FiniteFloat
    positive_days: int
    negative_days: int
    unchanged_days: int


class HistoricalPairReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["HISTORICAL_PRICE_REFERENCE_ONLY"] = "HISTORICAL_PRICE_REFERENCE_ONLY"
    first_session: date
    last_session: date
    observations: int
    return_observations: int
    currency: str
    price_basis: str
    candidate_subject_id: str
    alternative_subject_id: str
    candidate_source_label: str
    alternative_source_label: str
    candidate: HistoricalPriceStatistics
    alternative: HistoricalPriceStatistics
    daily_return_correlation: FiniteFloat | None
    calendar_coverage_verified: Literal[False] = False
    historical_vintage_verified: Literal[False] = False
    future_net_return_estimated: Literal[False] = False
    liquidity_cost_estimated: Literal[False] = False
    marginal_portfolio_risk_estimated: Literal[False] = False
    decision_authority: Literal[False] = False
    research_only: Literal[True] = True
    execution_allowed: Literal[False] = False


def _changes(series: HistoricalCloseSeries) -> tuple[list[float], list[float]]:
    closes = [x.close for x in series.closes]
    returns = [b / a - 1.0 for a, b in zip(closes[:-1], closes[1:])]
    if not all(math.isfinite(x) for x in returns):
        raise ValueError("nonfinite derived return")
    return closes, returns


def _statistics(closes: list[float], returns: list[float]) -> HistoricalPriceStatistics:
    peak = closes[0]
    drawdown = 0.0
    for close in closes:
        peak = max(peak, close)
        drawdown = max(drawdown, 1.0 - close / peak)
    return HistoricalPriceStatistics(
        price_change_pct=(closes[-1] / closes[0] - 1.0) * 100,
        daily_sample_sd_pct=stdev(returns) * 100,
        maximum_close_drawdown_pct=drawdown * 100,
        worst_daily_change_pct=min(returns) * 100,
        best_daily_change_pct=max(returns) * 100,
        positive_days=sum(x > 0 for x in returns),
        negative_days=sum(x < 0 for x in returns),
        unchanged_days=sum(x == 0 for x in returns),
    )


def historical_pair_reference(
    candidate: HistoricalCloseSeries,
    alternative: HistoricalCloseSeries,
    *,
    last_completed_session: date,
) -> HistoricalPairReference:
    """Compute an observed historical reference on exact common date labels.

    The caller must establish the last *completed* session, independently of
    the input. Future dates, missing terminal session and mismatched date sets
    are rejected. Even equal observed sets do not certify exchange-calendar
    completeness or point-in-time data availability.
    """
    if type(last_completed_session) is not date:
        raise ValueError("last_completed_session must be an explicit date")
    candidate = HistoricalCloseSeries.model_validate(candidate.model_dump())
    alternative = HistoricalCloseSeries.model_validate(alternative.model_dump())
    if candidate.subject_id == alternative.subject_id:
        raise ValueError("self comparison")
    if (candidate.currency, candidate.price_basis) != (alternative.currency, alternative.price_basis):
        raise ValueError("different currency or price basis")
    days = tuple(x.session for x in candidate.closes)
    if days != tuple(x.session for x in alternative.closes):
        raise ValueError("observed session sets differ; do not silently intersect")
    if days[-1] != last_completed_session:
        raise ValueError("last observed date differs from requested completed session")
    left, lr = _changes(candidate)
    right, rr = _changes(alternative)
    # A flat price series has undefined correlation, not zero correlation.
    corr = None if stdev(lr) == 0 or stdev(rr) == 0 else correlation(lr, rr)
    return HistoricalPairReference(
        first_session=days[0], last_session=days[-1],
        observations=len(days), return_observations=len(days)-1,
        currency=candidate.currency, price_basis=candidate.price_basis,
        candidate_subject_id=candidate.subject_id, alternative_subject_id=alternative.subject_id,
        candidate_source_label=candidate.source_label, alternative_source_label=alternative.source_label,
        candidate=_statistics(left, lr), alternative=_statistics(right, rr),
        daily_return_correlation=corr,
    )


def event_price_window_reference(candidate: HistoricalCloseSeries,
                                 benchmark: HistoricalCloseSeries, *,
                                 sessions: tuple[date, ...], event_session: date) -> dict:
    """Retrospective price-only event-window and market-model diagnostic.

    Fixed 30 estimation returns, five-session gap, 1/3/5-session event windows.
    Caller must establish the calendar and event reference session. No use of
    event-window observations to fit the model. Not causal, PIT, total-return,
    trading simulation or forecast evidence; no open-price decomposition.
    """
    if not sessions or type(event_session) is not date or any(type(d) is not date for d in sessions):
        raise ValueError("EVENT_EXPLICIT_SESSION_REQUIRED")
    reference = historical_pair_reference(candidate, benchmark, last_completed_session=sessions[-1])
    if reference.currency != "CNY" or reference.price_basis != "RAW_CLOSE":
        raise ValueError("EVENT_RAW_CNY_PRICE_REQUIRED")
    if tuple(row.session for row in candidate.closes) != sessions:
        raise ValueError("EVENT_SESSION_COVERAGE_INCOMPLETE")
    if event_session not in sessions:
        raise ValueError("EVENT_SESSION_NOT_IN_CALENDAR")
    index = sessions.index(event_session)
    estimation_count, gap = 30, 5
    first, last = index-gap-estimation_count, index-gap-1
    if first < 1 or index+4 >= len(sessions):
        raise ValueError("EVENT_WINDOW_HISTORY_INSUFFICIENT")
    a_prices, a_returns = _changes(candidate)
    b_prices, b_returns = _changes(benchmark)
    a_fit, b_fit = a_returns[first-1:last], b_returns[first-1:last]
    assert len(a_fit) == len(b_fit) == estimation_count
    mean_a, mean_b = math.fsum(a_fit)/estimation_count, math.fsum(b_fit)/estimation_count
    variance = math.fsum((b-mean_b)**2 for b in b_fit)
    if variance <= 0 or not math.isfinite(variance):
        raise ValueError("EVENT_ESTIMATION_BENCHMARK_FLAT_OR_INVALID")
    beta = math.fsum((a-mean_a)*(b-mean_b) for a,b in zip(a_fit,b_fit))/variance
    alpha = mean_a-beta*mean_b
    abnormal = [a_returns[t-1] - (alpha+beta*b_returns[t-1]) for t in range(index,index+5)]
    rows = []
    for horizon in (1, 3, 5):
        end = index+horizon-1
        a = (a_prices[end]/a_prices[index-1]-1)*100
        b = (b_prices[end]/b_prices[index-1]-1)*100
        rows.append({"sessions": horizon, "end_session": sessions[end].isoformat(),
            "candidate_close_return_pct": a, "benchmark_close_return_pct": b,
            "close_return_difference_pp": a-b,
            "market_model_arithmetic_car_pct": math.fsum(abnormal[:horizon])*100})
    values = [alpha, beta, *abnormal, *(v for row in rows for v in row.values() if isinstance(v,float))]
    if not all(math.isfinite(value) for value in values):
        raise ValueError("EVENT_NONFINITE_DIAGNOSTIC")
    return {"status": "RETROSPECTIVE_EVENT_PRICE_DIAGNOSTIC_ONLY",
        "candidate_subject_id": candidate.subject_id, "benchmark_subject_id": benchmark.subject_id,
        "event_session": event_session.isoformat(), "prior_close_session": sessions[index-1].isoformat(),
        "estimation_first_return_session": sessions[first].isoformat(),
        "estimation_last_return_session": sessions[last].isoformat(),
        "estimation_return_count": estimation_count, "estimation_gap_sessions": gap,
        "alpha_daily_decimal": alpha, "beta": beta, "windows": rows,
        "price_basis": "RAW_CLOSE_WITHOUT_DISTRIBUTIONS",
        "supplied_session_set_matched": True, "calendar_independently_verified": False,
        "corporate_action_coverage_verified": False, "historical_vintage_verified": False,
        "open_prices_available": False, "causal_effect_estimated": False,
        "statistical_significance_estimated": False, "future_return_estimated": False,
        "decision_authority": False, "research_only": True, "execution_allowed": False}
