import math
from datetime import UTC, date, datetime, timedelta

import pytest

from investment_evidence_engine.risk_evidence_guards import (
    aggregate_status,
    aligned_period_indices,
    complete_nonnegative_max,
    complete_nonnegative_sum,
    finite,
    fresh_observation_epoch,
    growth_pct,
    high_risk,
    period_day,
    positive_ratio_minus_one,
)


@pytest.mark.parametrize("bad", [None, True, math.nan, math.inf, -math.inf, "unknown"])
def test_invalid_is_not_zero(bad):
    assert finite(bad) is None
    assert complete_nonnegative_sum((1, bad)) is None
    assert complete_nonnegative_max((1, bad)) is None


def test_explicit_zero_and_partial_amount():
    assert complete_nonnegative_sum((0, 0, 0)) == 0
    assert complete_nonnegative_sum((1, 2, 0)) == 3
    assert complete_nonnegative_sum((1, -1)) is None
    assert complete_nonnegative_max((0, 2)) == 2
    assert complete_nonnegative_max(()) is None
    assert complete_nonnegative_max((2, -1)) is None
    assert complete_nonnegative_sum((1e308, 1e308)) is None


def test_growth_requires_comparable_denominator():
    assert growth_pct(0, 10) == -100
    assert growth_pct(10, 10) == 0
    assert growth_pct(10, 0) is None
    assert growth_pct(10, None) is None
    assert growth_pct(None, 10) is None
    assert growth_pct(-1, 10) is None


def test_partial_risk_not_clean_and_known_alert_retained():
    assert high_risk(((1, 2, 3), (None, 2, 3))) == "UNKNOWN"
    assert high_risk(((2.5, 2, 3), (None, 2, 3))) == "WARN"
    assert high_risk(((None, 2, 3), (4, 2, 3))) == "RED_FLAG"
    assert high_risk(((2, 2, 3), (1, 2, 3))) == "PASS"
    assert high_risk(((3, 2, 3),)) == "WARN"
    with pytest.raises(ValueError):
        high_risk(((1, 3, 2),))


def test_aggregate_never_clean_with_missing_rule():
    assert aggregate_status(("PASS",)*30) == "CLEAN"
    assert aggregate_status(("PASS",)*29+("UNKNOWN",)) == "UNKNOWN"
    assert aggregate_status(("UNKNOWN", "WARN")) == "WARN"
    assert aggregate_status(("WARN", "RED_FLAG", "UNKNOWN")) == "RED_FLAG"
    with pytest.raises(ValueError):
        aggregate_status(())


def test_period_identity_and_alignment():
    cutoff = date(2026, 11, 26)
    assert period_day("20260930", cutoff=cutoff) == "2026-09-30"
    assert period_day("2026-09-30 00:00:00", cutoff=cutoff) == "2026-09-30"
    for bad in (None, "2026-09-30junk", "2026-02-30", "2026-12-31", "NaT"):
        assert period_day(bad, cutoff=cutoff) is None
    values = ("20250630", "20260930", "20260630", "20250930", "20261231")
    assert aligned_period_indices(values, cutoff=cutoff) == ((1, 2, 3, 0), "2026-09-30")
    assert aligned_period_indices(values, cutoff=cutoff, anchor="2026-06-30") == ((2, 3, 0), "2026-06-30")
    assert aligned_period_indices(values, cutoff=cutoff, anchor="2026-03-31") == ((), "2026-03-31")
    assert aligned_period_indices(values + ("20260930",), cutoff=cutoff) == ((), None)


def test_cache_age_and_exchange_day_boundary():
    first = datetime(2026, 11, 26, 15, 59, tzinfo=UTC)
    stamp = first.timestamp()
    assert fresh_observation_epoch(stamp, (first+timedelta(seconds=30)).timestamp(), ttl_seconds=60)
    assert not fresh_observation_epoch(stamp, (first+timedelta(seconds=60)).timestamp(), ttl_seconds=120)
    assert not fresh_observation_epoch(stamp, stamp-1, ttl_seconds=60)
    assert not fresh_observation_epoch(stamp, stamp+61, ttl_seconds=60)
    assert not fresh_observation_epoch(float("nan"), stamp, ttl_seconds=60)


def test_positive_reference_ratio():
    assert positive_ratio_minus_one(99, 100) == pytest.approx(-0.01)
    assert positive_ratio_minus_one(100, 100) == 0
    assert positive_ratio_minus_one(200, 100, denominator_scale=2) == 0


@pytest.mark.parametrize("args", [
    (0, 100, 1), (100, 0, 1), (-1, 1, 1), (1, 1, 0),
    (math.inf, 1, 1), (1, math.inf, 1), (1, 1, math.nan),
    (1, 1e308, 1e308), (1, 1e-308, 1e-308), (1e308, 1e-308, 1),
    (None, 1, 1), (True, 1, 1),
])
def test_invalid_reference_ratio_is_unknown(args):
    num, den, scale = args
    assert positive_ratio_minus_one(num, den, denominator_scale=scale) is None
