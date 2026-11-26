from datetime import date, timedelta

import pytest

from investment_evidence_engine.historical_reference import (
    DailyClose,
    HistoricalCloseSeries,
    historical_pair_reference,
)

START = date(2026, 1, 5)
DAYS = tuple(START + timedelta(days=i) for i in range(23))


def series(subject, prices, *, days=DAYS, currency="CNY", basis="RAW_CLOSE"):
    return HistoricalCloseSeries(
        subject_id=subject, currency=currency, price_basis=basis, source_label="synthetic only",
        closes=tuple(DailyClose(session=d, close=float(p)) for d, p in zip(days, prices)),
    )


def test_historical_reference_has_correct_statistics_and_no_forecast_authority():
    # A single 20% fall followed by a recovery; all other changes zero.
    left = series("A", [100, 80] + [100] * 21)
    right = series("B", [100] * 23)
    ref = historical_pair_reference(left, right, last_completed_session=DAYS[-1])
    assert ref.observations == 23 and ref.return_observations == 22
    assert ref.candidate.price_change_pct == 0
    assert ref.candidate.maximum_close_drawdown_pct == pytest.approx(20)
    assert ref.candidate.worst_daily_change_pct == pytest.approx(-20)
    assert ref.candidate.best_daily_change_pct == pytest.approx(25)
    assert ref.candidate.positive_days == 1 and ref.candidate.negative_days == 1
    assert ref.candidate.unchanged_days == 20
    assert ref.daily_return_correlation is None
    assert not ref.calendar_coverage_verified and not ref.historical_vintage_verified
    assert not ref.future_net_return_estimated and not ref.liquidity_cost_estimated
    assert not ref.marginal_portfolio_risk_estimated and not ref.decision_authority
    assert ref.research_only and not ref.execution_allowed


def test_scaled_prices_have_identical_return_statistics():
    prices = [10 + (i % 3) for i in range(23)]
    ref = historical_pair_reference(series("A", prices), series("B", [p*2 for p in prices]),
                                    last_completed_session=DAYS[-1])
    assert ref.daily_return_correlation == pytest.approx(1)
    assert ref.candidate == ref.alternative


@pytest.mark.parametrize("fault", ["missing", "future", "stale", "different_currency",
    "different_basis", "same_id", "invalid_value", "duplicate", "unsorted", "too_short"])
def test_incomparable_inputs_rejected(fault):
    with pytest.raises(ValueError):
        left = series("A", [10] * 23)
        right = series("B", [11] * 23)
        cutoff = DAYS[-1]
        if fault == "missing":
            right = series("B", [11]*22, days=DAYS[:5]+DAYS[6:])
        elif fault == "future":
            cutoff = DAYS[-2]
        elif fault == "stale":
            cutoff += timedelta(days=1)
        elif fault == "different_currency":
            right = series("B", [11]*23, currency="USD")
        elif fault == "different_basis":
            right = series("B", [11]*23, basis="PROVIDER_ADJUSTED_CLOSE_NOT_VINTAGE_VERIFIED")
        elif fault == "same_id":
            right = series("A", [11]*23)
        elif fault == "invalid_value":
            right = series("B", [11]*22+[float("nan")])
        elif fault == "duplicate":
            right = series("B", [11]*23, days=DAYS[:-1]+(DAYS[-2],))
        elif fault == "unsorted":
            right = series("B", [11]*23, days=tuple(reversed(DAYS)))
        elif fault == "too_short":
            right = series("B", [11]*20, days=DAYS[:20])
        historical_pair_reference(left, right, last_completed_session=cutoff)


def test_model_copy_cannot_bypass_finite_positive_values():
    a = series("A", [10]*23)
    b = series("B", [11]*23)
    bad = b.model_copy(update={"closes": b.closes[:-1]+(b.closes[-1].model_copy(update={"close": 0.0}),)})
    with pytest.raises(ValueError):
        historical_pair_reference(a, bad, last_completed_session=DAYS[-1])
