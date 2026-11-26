from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from investment_evidence_engine.comparison_math import (
    COMPARISON_DIMENSIONS,
    ComparableOpportunityMetrics,
    ComparisonBasis,
    compare_metrics,
)


def basis(**changes):
    values = {
        "as_of": datetime(2026, 1, 1, tzinfo=UTC),
        "horizon_days": 30,
        "currency": "CNY",
        "benchmark_id": "SYNTHETIC_BENCHMARK",
        "net_return_definition": "synthetic net total return",
        "downside_risk_definition": "synthetic expected shortfall",
        "liquidity_definition": "synthetic all-in friction",
        "marginal_risk_definition": "synthetic change in risk",
        "comparison_context_id": "SYNTHETIC_CONTEXT",
    }
    return ComparisonBasis(**(values | changes))


def metrics(subject, **changes):
    values = {
        "subject_id": subject,
        "basis": basis(),
        "expected_net_return_pct": 3.0,
        "downside_risk_pct": 2.0,
        "liquidity_cost_bps": 10.0,
        "marginal_portfolio_risk_pct": -0.5,
    }
    return ComparableOpportunityMetrics(**(values | changes))


def test_four_directions_are_not_a_composite_score():
    left = metrics("synthetic-A")
    right = metrics(
        "synthetic-B",
        expected_net_return_pct=2.0,
        downside_risk_pct=1.0,
        liquidity_cost_bps=20.0,
        marginal_portfolio_risk_pct=-1.0,
    )
    result = compare_metrics(left, right)
    assert result.dimensions_compared == COMPARISON_DIMENSIONS
    assert result.candidate_advantages == (
        "EXPECTED_NET_RETURN_PCT_HIGHER",
        "LIQUIDITY_COST_BPS_LOWER",
    )
    assert result.alternative_advantages == (
        "DOWNSIDE_RISK_PCT_LOWER",
        "MARGINAL_PORTFOLIO_RISK_PCT_LOWER",
    )
    assert not result.reasons
    swapped = compare_metrics(right, left)
    assert swapped.candidate_advantages == result.alternative_advantages
    assert swapped.alternative_advantages == result.candidate_advantages


@pytest.mark.parametrize(
    "change",
    [
        {"as_of": datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=1)},
        {"horizon_days": 31},
        {"currency": "USD"},
        {"benchmark_id": "OTHER"},
        {"net_return_definition": "gross return"},
        {"downside_risk_definition": "other risk"},
        {"liquidity_definition": "other friction"},
        {"marginal_risk_definition": "other risk change"},
        {"comparison_context_id": "OTHER_CONTEXT"},
    ],
)
def test_any_basis_mismatch_withholds_all_advantages(change):
    result = compare_metrics(metrics("A"), metrics("B", basis=basis(**change)))
    assert result.reasons == ("COMPARISON_BASIS_MISMATCH",)
    assert not result.dimensions_compared
    assert not result.candidate_advantages
    assert not result.alternative_advantages


def test_equal_values_do_not_generate_advantages():
    result = compare_metrics(metrics("A"), metrics("B"))
    assert result.dimensions_compared == COMPARISON_DIMENSIONS
    assert not result.candidate_advantages and not result.alternative_advantages
    assert compare_metrics(metrics("A"), metrics("A")).reasons == ("SELF_COMPARISON",)


@pytest.mark.parametrize(
    "change",
    [
        {"expected_net_return_pct": float("nan")},
        {"downside_risk_pct": -1.0},
        {"liquidity_cost_bps": float("inf")},
        {"marginal_portfolio_risk_pct": True},
        {"basis": basis().model_copy(update={"horizon_days": 0})},
    ],
)
def test_revalidation_blocks_unsafe_model_copies(change):
    invalid = metrics("A").model_copy(update=change)
    result = compare_metrics(invalid, metrics("B"))
    assert result.reasons == ("INVALID_COMPARABLE_METRICS",)
    assert not result.dimensions_compared


def test_missing_metrics_or_naive_time_cannot_be_admitted():
    with pytest.raises(ValidationError):
        ComparableOpportunityMetrics(subject_id="A", basis=basis())
    with pytest.raises(ValidationError):
        basis(as_of=datetime(2026, 1, 1))
