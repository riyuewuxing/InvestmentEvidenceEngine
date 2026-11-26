import math

import pytest

from investment_evidence_engine.risk_evidence_guards import (
    aggregate_status,
    complete_nonnegative_max,
    complete_nonnegative_sum,
    finite,
    growth_pct,
    high_risk,
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
