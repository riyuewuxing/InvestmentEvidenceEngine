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
