"""Pure comparison of already supplied, identically defined research metrics.

This module does not acquire observations, forecast returns, admit evidence, rank
assets, read portfolio records, or authorize decisions. Only synthetic fixtures
are used in public regression; private evidence binding belongs to the caller.
"""
from __future__ import annotations

from dataclasses import dataclass

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, FiniteFloat, ValidationError


class ComparisonBasis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, str_strip_whitespace=True)

    as_of: AwareDatetime
    horizon_days: int = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    benchmark_id: str = Field(min_length=1)
    net_return_definition: str = Field(min_length=1)
    downside_risk_definition: str = Field(min_length=1)
    liquidity_definition: str = Field(min_length=1)
    marginal_risk_definition: str = Field(min_length=1)
    comparison_context_id: str = Field(min_length=1)


class ComparableOpportunityMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, str_strip_whitespace=True)

    subject_id: str = Field(min_length=1)
    basis: ComparisonBasis
    expected_net_return_pct: FiniteFloat
    downside_risk_pct: FiniteFloat = Field(ge=0)
    liquidity_cost_bps: FiniteFloat = Field(ge=0)
    marginal_portfolio_risk_pct: FiniteFloat


# These are four separately reported dimensions, never a composite score.
COMPARISON_DIMENSIONS = (
    "expected_net_return_pct",
    "downside_risk_pct",
    "liquidity_cost_bps",
    "marginal_portfolio_risk_pct",
)


@dataclass(frozen=True)
class RelativeMetricsComparison:
    candidate_advantages: tuple[str, ...] = ()
    alternative_advantages: tuple[str, ...] = ()
    dimensions_compared: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()


def compare_metrics(
    candidate: ComparableOpportunityMetrics, alternative: ComparableOpportunityMetrics
) -> RelativeMetricsComparison:
    """Compare directions only on identical bases; never infer missing metrics."""
    try:
        # Revalidate even model_copy/model_construct input, which can bypass validators.
        candidate = ComparableOpportunityMetrics.model_validate(candidate.model_dump())
        alternative = ComparableOpportunityMetrics.model_validate(alternative.model_dump())
    except (ValidationError, ValueError, TypeError, AttributeError):
        return RelativeMetricsComparison(reasons=("INVALID_COMPARABLE_METRICS",))
    if candidate.subject_id == alternative.subject_id:
        return RelativeMetricsComparison(reasons=("SELF_COMPARISON",))
    if candidate.basis != alternative.basis:
        return RelativeMetricsComparison(reasons=("COMPARISON_BASIS_MISMATCH",))

    candidate_advantages: list[str] = []
    alternative_advantages: list[str] = []
    for field in COMPARISON_DIMENSIONS:
        left = getattr(candidate, field)
        right = getattr(alternative, field)
        if left == right:
            continue
        higher_is_better = field == "expected_net_return_pct"
        label = field.upper() + ("_HIGHER" if higher_is_better else "_LOWER")
        if (left > right) == higher_is_better:
            candidate_advantages.append(label)
        else:
            alternative_advantages.append(label)
    return RelativeMetricsComparison(
        candidate_advantages=tuple(candidate_advantages),
        alternative_advantages=tuple(alternative_advantages),
        dimensions_compared=COMPARISON_DIMENSIONS,
    )
