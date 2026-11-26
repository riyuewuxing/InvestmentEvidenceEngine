import pytest

from investment_evidence_engine.price_adjustment_guard import checked_adjusted_close


def test_distinct_actions_apply_once():
    assert checked_adjusted_close(100.0, []) == 100.0
    assert checked_adjusted_close(100.0, [("f1", "a1", .5), ("f2", "a2", .9)]) == pytest.approx(45.)


@pytest.mark.parametrize("rows", [
    [("f1", "a1", .5), ("f1", "a1", .5)],
    [("f1", "a1", .5), ("f2", "a1", .6)],
    [("f1", "a1", .5), ("f1", "a2", .6)],
])
def test_duplicate_and_unresolved_revisions_fail_closed(rows):
    with pytest.raises(ValueError, match="DUPLICATE_OR_UNRESOLVED_REVISION"):
        checked_adjusted_close(100.0, rows)


@pytest.mark.parametrize("factor", [True, 0., -1., float("nan"), float("inf"), "0.5"])
def test_invalid_factor(factor):
    with pytest.raises(ValueError, match="FACTOR_INVALID"):
        checked_adjusted_close(100.0, [("f1", "a1", factor)])


@pytest.mark.parametrize("rows", [
    [("f1", "a1", 1e200), ("f2", "a2", 1e200)],
    [("f1", "a1", 1e-200), ("f2", "a2", 1e-200)],
])
def test_cumulative_overflow_or_underflow(rows):
    with pytest.raises(ValueError, match="MULTIPLIER_NONFINITE_OR_NONPOSITIVE"):
        checked_adjusted_close(100.0, rows)


@pytest.mark.parametrize("raw, factor", [(1e200, 1e200), (1e-200, 1e-200)])
def test_result_overflow_or_underflow(raw, factor):
    with pytest.raises(ValueError, match="RESULT_NONFINITE_OR_NONPOSITIVE"):
        checked_adjusted_close(raw, [("f1", "a1", factor)])


@pytest.mark.parametrize("raw", [0., -1., True, float("nan"), float("inf"), 10**1000])
def test_bad_raw_close(raw):
    with pytest.raises(ValueError, match="RAW_CLOSE_INVALID"):
        checked_adjusted_close(raw, [])


def test_invalid_ids_fail_closed():
    with pytest.raises(ValueError, match="IDENTITY_INVALID"):
        checked_adjusted_close(100.0, [(" ", "a1", .5)])
